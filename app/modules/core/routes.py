from flask import render_template, request, redirect, session, jsonify
from app import db, global_bot, global_loop
from app.models import User, Chat, DEFAULT_FIELDS, DEFAULT_SYSTEM
from app.services import get_conf, set_conf
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from . import core_bp
import os, jwt, time, json, asyncio, re
from datetime import datetime, timedelta

# =======================
# 🌐 网页路由部分
# =======================

@core_bp.route('/core')
@core_bp.route('/core/')
def index():
    if not session.get('logged_in'): return render_template('base.html', page='login')
    return redirect('/core/users')

@core_bp.route('/core/users')
def page_users():
    if not session.get('logged_in'): return redirect('/core')
    q = request.args.get('q', '')
    query = User.query
    if q: query = query.filter(User.profile_data.contains(q))
    users = query.order_by(User.id.desc()).all()
    fields = get_conf('fields', DEFAULT_FIELDS)
    return render_template('users.html', page='users', users=users, fields=fields, q=q)

@core_bp.route('/core/fields')
def page_fields():
    if not session.get('logged_in'): return redirect('/core')
    fields = get_conf('fields', DEFAULT_FIELDS)
    return render_template('fields.html', page='fields', fields=fields, fields_json=json.dumps(fields))

@core_bp.route('/core/system')
def page_system():
    if not session.get('logged_in'): return redirect('/core')
    sys = get_conf('system', DEFAULT_SYSTEM)
    fields = get_conf('fields', DEFAULT_FIELDS)
    
    # 🆕 获取所有已发现的群组和频道
    groups = Chat.query.filter(Chat.type.in_(['group', 'supergroup'])).all()
    channels = Chat.query.filter_by(type='channel').all()
    
    return render_template('system.html', page='system', sys=sys, fields=fields, groups=groups, channels=channels)

@core_bp.route('/core/magic_login')
def magic_login():
    token = request.args.get('token')
    if token and jwt.decode(token, os.getenv('SECRET_KEY'), algorithms=['HS256']).get('uid') == int(os.getenv('ADMIN_ID', 0)):
        session['logged_in'] = True
        return redirect('/core/users')
    return "Link Invalid", 403

@core_bp.route('/core/logout')
def logout(): session.clear(); return redirect('/core')

# =======================
# 📡 API 接口部分
# =======================

@core_bp.route('/core/api/save_user', methods=['POST'])
def api_save_user():
    if not session.get('logged_in'): return jsonify({"status":"err"}), 403
    data = request.json
    try:
        tg_id = int(data.get('tg_id'))
        user = User.query.filter_by(tg_id=tg_id).first()
        if not user:
            user = User(tg_id=tg_id)
            db.session.add(user)
        user.profile_data = json.dumps(data.get('profile', {}), ensure_ascii=False)
        days = int(data.get('add_days', 0))
        if days:
            now = datetime.now()
            base = user.expiration_date if (user.expiration_date and user.expiration_date > now) else now
            user.expiration_date = base + timedelta(days=days)
        db.session.commit()
        return jsonify({"status": "ok"})
    except Exception as e: return jsonify({"status": "err", "msg": str(e)})

@core_bp.route('/core/api/delete_user', methods=['POST'])
def api_delete_user():
    if not session.get('logged_in'): return jsonify({"status":"err"}), 403
    User.query.filter_by(id=request.json.get('id')).delete()
    db.session.commit()
    return jsonify({"status": "ok"})

@core_bp.route('/core/api/save_fields', methods=['POST'])
def api_save_fields():
    if not session.get('logged_in'): return jsonify({"status":"err"}), 403
    set_conf('fields', request.json)
    return jsonify({"status": "ok"})

@core_bp.route('/core/api/save_system', methods=['POST'])
def api_save_system():
    if not session.get('logged_in'): return jsonify({"status":"err"}), 403
    curr = get_conf('system', DEFAULT_SYSTEM)
    curr.update(request.json)
    set_conf('system', curr)
    return jsonify({"status": "ok"})

@core_bp.route('/core/api/push_user', methods=['POST'])
def api_push_user():
    if not session.get('logged_in'): return jsonify({"status":"err"}), 403
    import app
    
    uid = request.json.get('id')
    user = User.query.filter_by(id=uid).first()
    sys = get_conf('system', DEFAULT_SYSTEM)
    channel = sys.get('push_channel_id')
    
    if not channel: return jsonify({"status": "err", "msg": "请先在系统设置中选择推送频道"})
    
    tpl = sys.get('template', '')
    fields_map = {f['key']: f['label'] for f in get_conf('fields', DEFAULT_FIELDS)}
    try:
        data = json.loads(user.profile_data)
        line = tpl.replace("{onlineEmoji}", sys.get('online_emoji',''))
        for k, v in data.items():
            if k in fields_map: line = line.replace(f"{{{fields_map[k]}}}", str(v))
        line = re.sub(r'\{.*?\}', '', line)
        
        if app.global_bot and app.global_loop:
            asyncio.run_coroutine_threadsafe(
                app.global_bot.send_message(chat_id=channel, text=line, parse_mode='HTML'),
                app.global_loop
            )
            return jsonify({"status": "ok", "msg": "已推送"})
    except Exception as e: return jsonify({"status": "err", "msg": str(e)})
    return jsonify({"status": "err", "msg": "Bot未连接"})

# =======================
# 🤖 机器人逻辑部分
# =======================

async def bot_start(update: Update, context):
    if update.effective_user.id == int(os.getenv('ADMIN_ID', 0)):
        token = jwt.encode({'uid': update.effective_user.id, 'exp': time.time()+3600}, os.getenv('SECRET_KEY'), algorithm='HS256')
        url = f"{os.getenv('RAILWAY_PUBLIC_DOMAIN')}/core/magic_login?token={token}"
        await update.message.reply_html(f"💼 <b>管理后台：</b>\n<a href='{url}'>点击进入</a>")

async def bot_handler(update: Update, context):
    if not update.effective_chat: return
    
    # 🆕 自动发现逻辑：记录群和频道
    chat = update.effective_chat
    if chat.type in ['group', 'supergroup', 'channel']:
        from app import create_app
        with create_app().app_context():
            # 检查数据库是否已存在，不存在则添加
            if not Chat.query.get(chat.id):
                try:
                    new_chat = Chat(id=chat.id, title=chat.title, type=chat.type)
                    db.session.add(new_chat)
                    db.session.commit()
                    print(f"✅ 发现新{chat.type}: {chat.title} ({chat.id})")
                except:
                    db.session.rollback()

    if not update.message or not update.message.text: return
    text = update.message.text.strip()
    user = update.effective_user
    sys_conf = get_conf('system', DEFAULT_SYSTEM)

    # 1. 认证用户发言自动点赞 (只在打卡群生效)
    target_group = str(sys_conf.get('checkin_chat_id', ''))
    current_chat_id = str(update.effective_chat.id)

    if sys_conf.get('auto_like') and (not target_group or current_chat_id == target_group):
        from app import create_app
        with create_app().app_context():
            if User.query.filter_by(tg_id=user.id).first():
                try: await update.message.set_reaction(sys_conf.get('like_emoji', '❤️'))
                except: pass

    # 2. 打卡逻辑
    if text == sys_conf.get('checkin_cmd', '打卡'):
        if not sys_conf.get('checkin_open'): return
        
        # 🆕 限制只能在指定群打卡 (如果设置了的话)
        if target_group and current_chat_id != target_group:
            return # 在其他群无视打卡指令

        from app import create_app
        with create_app().app_context():
            u = User.query.filter_by(tg_id=user.id).first()
            delay = int(sys_conf.get('checkin_del_time', 30))
            
            if not u: # 未认证
                msg = await update.message.reply_html(sys_conf.get('msg_not_registered'))
                context.job_queue.run_once(lambda c: c.job.data.delete(), delay, data=msg)
                return

            now = datetime.now()
            if u.checkin_time and u.checkin_time.date() == now.date():
                msg = await update.message.reply_html(sys_conf.get('msg_repeat_checkin'))
            else:
                u.checkin_time = now
                u.online = True
                db.session.commit()
                msg = await update.message.reply_html(sys_conf.get('msg_checkin_success'))
            
            try: context.job_queue.run_once(lambda c: c.job.data.delete(), delay, data=update.message)
            except: pass
            context.job_queue.run_once(lambda c: c.job.data.delete(), delay, data=msg)

    # 3. 查询逻辑 (仅今日)
    if text == sys_conf.get('query_cmd', '查询'):
        if not sys_conf.get('query_open'): return
        # 🆕 查询指令也只在指定群生效
        if target_group and current_chat_id != target_group: return

        from app import create_app
        with create_app().app_context():
            today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            users = User.query.filter(User.checkin_time >= today_start, User.online == True).all()
            
            delay = int(sys_conf.get('query_del_time', 30))
            if not users:
                msg = await update.message.reply_text("😢 今日暂无打卡")
            else:
                header = sys_conf.get('msg_query_header', '')
                tpl = sys_conf.get('template', '')
                fields_map = {f['key']: f['label'] for f in get_conf('fields', DEFAULT_FIELDS)}
                lines = []
                for u in users:
                    try:
                        d = json.loads(u.profile_data)
                        line = tpl.replace("{onlineEmoji}", sys_conf.get('online_emoji',''))
                        for k, l in fields_map.items():
                            line = line.replace(f"{{{l}}}", str(d.get(k,'')))
                        lines.append(re.sub(r'\{.*?\}', '', line))
                    except: continue
                msg = await update.message.reply_html(header + "\n\n".join(lines))
            
            try: context.job_queue.run_once(lambda c: c.job.data.delete(), delay, data=update.message)
            except: pass
            context.job_queue.run_once(lambda c: c.job.data.delete(), delay, data=msg)

async def run_bot():
    import app 
    token = os.getenv('TOKEN')
    if not token: return
    app_bot = Application.builder().token(token).build()
    
    app.global_bot = app_bot.bot
    app.global_loop = asyncio.get_running_loop()
    
    app_bot.add_handler(CommandHandler("start", bot_start))
    app_bot.add_handler(MessageHandler(filters.ALL, bot_handler)) # ⚠️ 改为 filters.ALL 以监听所有消息来发现群
    
    await app_bot.initialize()
    await app_bot.start()
    await app_bot.updater.start_polling()
    await asyncio.Event().wait()
