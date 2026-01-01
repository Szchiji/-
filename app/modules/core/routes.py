from flask import Blueprint, render_template, request, redirect, session, jsonify
from app import db, global_bot, global_loop
from app.models import User, DEFAULT_FIELDS, DEFAULT_SYSTEM
from app.services import get_conf, set_conf
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters
import os, jwt, time, json, asyncio, re, threading
from datetime import datetime, timedelta

# 创建模块蓝图
core_bp = Blueprint('core', __name__, url_prefix='/core', template_folder='templates')

# --- 网页路由 ---

@core_bp.route('/')
def index():
    if not session.get('logged_in'): return render_template('base.html', page='login')
    return redirect('/core/users')

@core_bp.route('/users')
def page_users():
    if not session.get('logged_in'): return redirect('/core')
    q = request.args.get('q', '')
    query = User.query
    if q: query = query.filter(User.profile_data.contains(q))
    users = query.order_by(User.id.desc()).all()
    fields = get_conf('fields', DEFAULT_FIELDS)
    return render_template('users.html', page='users', users=users, fields=fields, q=q)

@core_bp.route('/fields')
def page_fields():
    if not session.get('logged_in'): return redirect('/core')
    fields = get_conf('fields', DEFAULT_FIELDS)
    return render_template('fields.html', page='fields', fields=fields, fields_json=json.dumps(fields))

@core_bp.route('/system')
def page_system():
    if not session.get('logged_in'): return redirect('/core')
    sys = get_conf('system', DEFAULT_SYSTEM)
    fields = get_conf('fields', DEFAULT_FIELDS)
    return render_template('system.html', page='system', sys=sys, fields=fields)

@core_bp.route('/magic_login')
def magic_login():
    token = request.args.get('token')
    if token and jwt.decode(token, os.getenv('SECRET_KEY'), algorithms=['HS256']).get('uid') == int(os.getenv('ADMIN_ID')):
        session['logged_in'] = True
        return redirect('/core/users')
    return "Link Invalid", 403

@core_bp.route('/logout')
def logout(): session.clear(); return redirect('/core')

# --- API 接口 ---

@core_bp.route('/api/save_user', methods=['POST'])
def api_save_user():
    if not session.get('logged_in'): return jsonify({"status":"err", "msg":"403"}), 403
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

@core_bp.route('/api/delete_user', methods=['POST'])
def api_delete_user():
    if not session.get('logged_in'): return jsonify({"status":"err"}), 403
    User.query.filter_by(id=request.json.get('id')).delete()
    db.session.commit()
    return jsonify({"status": "ok"})

@core_bp.route('/api/save_fields', methods=['POST'])
def api_save_fields():
    if not session.get('logged_in'): return jsonify({"status":"err"}), 403
    set_conf('fields', request.json)
    return jsonify({"status": "ok"})

@core_bp.route('/api/save_system', methods=['POST'])
def api_save_system():
    if not session.get('logged_in'): return jsonify({"status":"err"}), 403
    curr = get_conf('system', DEFAULT_SYSTEM)
    curr.update(request.json)
    set_conf('system', curr)
    return jsonify({"status": "ok"})

@core_bp.route('/api/push_user', methods=['POST'])
def api_push_user():
    if not session.get('logged_in'): return jsonify({"status":"err"}), 403
    # 延迟导入防止循环引用
    import app
    
    uid = request.json.get('id')
    user = User.query.filter_by(id=uid).first()
    sys = get_conf('system', DEFAULT_SYSTEM)
    channel = sys.get('push_channel_id')
    
    if not channel: return jsonify({"status": "err", "msg": "未设置推送频道ID"})
    
    # 简单的模板替换
    tpl = sys.get('template', '')
    fields_map = {f['key']: f['label'] for f in get_conf('fields', DEFAULT_FIELDS)}
    try:
        data = json.loads(user.profile_data)
        line = tpl.replace("{onlineEmoji}", sys.get('online_emoji',''))
        for k, v in data.items():
            if k in fields_map: line = line.replace(f"{{{fields_map[k]}}}", str(v))
        line = re.sub(r'\{.*?\}', '', line) # 清理未匹配变量
        
        if app.global_bot and app.global_loop:
            asyncio.run_coroutine_threadsafe(
                app.global_bot.send_message(chat_id=channel, text=line, parse_mode='HTML'),
                app.global_loop
            )
            return jsonify({"status": "ok", "msg": "已推送"})
    except Exception as e: return jsonify({"status": "err", "msg": str(e)})
    return jsonify({"status": "err", "msg": "Bot未连接"})


# --- 机器人逻辑 ---

async def bot_start(update: Update, context):
    if update.effective_user.id == int(os.getenv('ADMIN_ID', 0)):
        token = jwt.encode({'uid': update.effective_user.id, 'exp': time.time()+3600}, os.getenv('SECRET_KEY'), algorithm='HS256')
        url = f"{os.getenv('RAILWAY_PUBLIC_DOMAIN')}/core/magic_login?token={token}"
        await update.message.reply_html(f"💼 <b>管理后台：</b>\n<a href='{url}'>点击进入</a>")

async def bot_handler(update: Update, context):
    if not update.message or not update.message.text: return
    text = update.message.text.strip()
    user = update.effective_user
    sys_conf = get_conf('system', DEFAULT_SYSTEM)

    # 1. 认证用户发言点赞
    if sys_conf.get('auto_like'):
        from app import create_app
        with create_app().app_context():
            if User.query.filter_by(tg_id=user.id).first():
                try: await update.message.set_reaction(sys_conf.get('like_emoji', '❤️'))
                except: pass

    # 2. 打卡
    if text == sys_conf.get('checkin_cmd', '打卡'):
        if not sys_conf.get('checkin_open'): return
        from app import create_app
        with create_app().app_context():
            u = User.query.filter_by(tg_id=user.id).first()
            delay = int(sys_conf.get('checkin_del_time', 30))
            
            if not u: # 未认证
                msg = await update.message.reply_html(sys_conf.get('msg_not_registered'))
                context.job_queue.run_once(lambda c: c.job.data.delete(), delay, data=msg)
                return

            now = datetime.now()
            # 简单去重：同日期算重复
            if u.checkin_time and u.checkin_time.date() == now.date():
                msg = await update.message.reply_html(sys_conf.get('msg_repeat_checkin'))
            else:
                u.checkin_time = now
                u.online = True
                db.session.commit()
                msg = await update.message.reply_html(sys_conf.get('msg_checkin_success'))
            
            # 删除用户指令和回复
            try: context.job_queue.run_once(lambda c: c.job.data.delete(), delay, data=update.message)
            except: pass
            context.job_queue.run_once(lambda c: c.job.data.delete(), delay, data=msg)

    # 3. 查询
    if text == sys_conf.get('query_cmd', '查询'):
        if not sys_conf.get('query_open'): return
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
    app_bot.add_handler(MessageHandler(filters.TEXT, bot_handler))
    
    await app_bot.initialize()
    await app_bot.start()
    await app_bot.updater.start_polling()
    await asyncio.Event().wait()
