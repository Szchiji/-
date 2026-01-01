from flask import Blueprint, render_template, request, redirect, session, jsonify, g
from app import db
from app.models import BotGroup, GroupUser, DEFAULT_FIELDS, DEFAULT_SYSTEM
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters
import os, jwt, time, json, asyncio, re
from datetime import datetime, timedelta

core_bp = Blueprint('core', __name__, url_prefix='/core', template_folder='templates')

# --- 上下文处理器：修复侧边栏消失 ---
@core_bp.context_processor
def inject_context():
    data = {'all_groups': []}
    if session.get('logged_in'):
        data['all_groups'] = BotGroup.query.order_by(BotGroup.updated_at.desc()).all()
    gid = session.get('current_group_id')
    if gid:
        data['current_group'] = BotGroup.query.get(gid)
    return data

# --- 辅助函数 ---
def get_group_conf(group):
    conf = DEFAULT_SYSTEM.copy()
    if group.config:
        try:
            c = json.loads(group.config)
            for k, v in c.items():
                if v is not None: conf[k] = v
        except: pass
    return conf

def get_group_fields(group):
    if group.fields_config:
        try: return json.loads(group.fields_config)
        except: pass
    return DEFAULT_FIELDS

# =======================
# 🌐 网页路由
# =======================

@core_bp.route('/')
def index():
    if not session.get('logged_in'): return render_template('base.html', page='login')
    return redirect('/core/select_group')

@core_bp.route('/select_group')
def page_select_group():
    if not session.get('logged_in'): return redirect('/core')
    session.pop('current_group_id', None) # 清除选中状态
    groups = BotGroup.query.order_by(BotGroup.updated_at.desc()).all()
    return render_template('select_group.html', groups=groups)

@core_bp.route('/group/<int:gid>/dashboard')
def page_dashboard(gid):
    if not session.get('logged_in'): return redirect('/core')
    session['current_group_id'] = gid
    group = BotGroup.query.get_or_404(gid)
    stats = {
        'users': GroupUser.query.filter_by(group_id=gid).count(),
        'online': GroupUser.query.filter_by(group_id=gid, online=True).count()
    }
    return render_template('dashboard.html', page='dashboard', group=group, stats=stats)

@core_bp.route('/group/<int:gid>/users')
def page_users(gid):
    if not session.get('logged_in'): return redirect('/core')
    session['current_group_id'] = gid
    group = BotGroup.query.get_or_404(gid)
    users = GroupUser.query.filter_by(group_id=gid).order_by(GroupUser.id.desc()).all()
    fields = get_group_fields(group)
    return render_template('users.html', page='users', group=group, users=users, fields=fields)

@core_bp.route('/group/<int:gid>/fields')
def page_fields(gid):
    if not session.get('logged_in'): return redirect('/core')
    session['current_group_id'] = gid
    group = BotGroup.query.get_or_404(gid)
    fields = get_group_fields(group)
    return render_template('fields.html', page='fields', group=group, fields=fields, fields_json=json.dumps(fields))

@core_bp.route('/group/<int:gid>/settings')
def page_settings(gid):
    if not session.get('logged_in'): return redirect('/core')
    session['current_group_id'] = gid
    group = BotGroup.query.get_or_404(gid)
    conf = get_group_conf(group)
    fields = get_group_fields(group)
    # 获取所有频道
    channels = BotGroup.query.filter_by(type='channel').all()
    return render_template('settings.html', page='settings', group=group, conf=conf, fields=fields, channels=channels)

# =======================
# 📡 API 路由 (加固版)
# =======================

@core_bp.route('/api/save_user', methods=['POST'])
def api_save_user():
    if not session.get('logged_in'): return jsonify({"status":"err"}), 403
    data = request.json
    # 优先使用前端传来的 group_id，没有则用 session
    gid = data.get('group_id') or session.get('current_group_id')
    if not gid: return jsonify({"status":"err", "msg": "No group id"})
    
    try:
        tg_id = int(data.get('tg_id'))
        user = GroupUser.query.filter_by(group_id=gid, tg_id=tg_id).first()
        if not user:
            user = GroupUser(group_id=gid, tg_id=tg_id)
            db.session.add(user)
        user.profile_data = json.dumps(data.get('profile', {}), ensure_ascii=False)
        db.session.commit()
        return jsonify({"status": "ok"})
    except Exception as e: return jsonify({"status": "err", "msg": str(e)})

@core_bp.route('/api/delete_user', methods=['POST'])
def api_delete_user():
    if not session.get('logged_in'): return jsonify({"status":"err"}), 403
    GroupUser.query.filter_by(id=request.json.get('id')).delete()
    db.session.commit()
    return jsonify({"status": "ok"})

@core_bp.route('/api/save_settings', methods=['POST'])
def api_save_settings():
    if not session.get('logged_in'): return jsonify({"status":"err"}), 403
    data = request.json
    gid = data.get('group_id') or session.get('current_group_id')
    group = BotGroup.query.get(gid)
    if group:
        # 移除 group_id 字段，剩下的存入 config
        if 'group_id' in data: del data['group_id']
        clean = {k: v for k, v in data.items() if v is not None}
        group.config = json.dumps(clean, ensure_ascii=False)
        db.session.commit()
    return jsonify({"status": "ok"})

@core_bp.route('/api/save_fields', methods=['POST'])
def api_save_fields():
    if not session.get('logged_in'): return jsonify({"status":"err"}), 403
    gid = request.json.get('group_id') or session.get('current_group_id')
    group = BotGroup.query.get(gid)
    if group:
        fields_data = request.json.get('fields', [])
        group.fields_config = json.dumps(fields_data, ensure_ascii=False)
        db.session.commit()
    return jsonify({"status": "ok"})

@core_bp.route('/api/push_user', methods=['POST'])
def api_push_user():
    if not session.get('logged_in'): return jsonify({"status":"err"}), 403
    import app
    gid = session.get('current_group_id')
    uid = request.json.get('id')
    
    group = BotGroup.query.get(gid)
    user = GroupUser.query.get(uid)
    conf = get_group_conf(group)
    
    channel_id = conf.get('push_channel_id')
    if not channel_id: return jsonify({"status": "err", "msg": "未配置推送频道"})
    
    tpl = conf.get('push_template', '{昵称} | {地区}')
    fields_map = {f['key']: f['label'] for f in get_group_fields(group)}
    
    try:
        data = json.loads(user.profile_data)
        line = tpl.replace("{onlineEmoji}", conf.get('online_emoji',''))
        # 替换普通变量
        for k, l in fields_map.items():
            line = line.replace(f"{{{l}}}", str(data.get(k,'')))
        
        # 替换 tg_id
        line = line.replace("{tg_id}", str(user.tg_id))
        
        # 清理残余
        line = re.sub(r'\{.*?\}', '', line)
        
        if app.global_bot and app.global_loop:
            asyncio.run_coroutine_threadsafe(
                app.global_bot.send_message(chat_id=channel_id, text=line, parse_mode='HTML'),
                app.global_loop
            )
            return jsonify({"status": "ok", "msg": "✅ 已推送"})
    except Exception as e: return jsonify({"status": "err", "msg": str(e)})
    return jsonify({"status": "err", "msg": "Bot未连接"})

@core_bp.route('/api/toggle_group', methods=['POST'])
def api_toggle_group():
    if not session.get('logged_in'): return jsonify({"status":"err"}), 403
    group = BotGroup.query.get(request.json.get('id'))
    if group:
        group.is_active = request.json.get('active')
        db.session.commit()
    return jsonify({"status": "ok"})

@core_bp.route('/magic_login')
def magic_login():
    token = request.args.get('token')
    try:
        if jwt.decode(token, os.getenv('SECRET_KEY'), algorithms=['HS256']).get('uid') == int(os.getenv('ADMIN_ID', 0)):
            session['logged_in'] = True
            return redirect('/core/select_group')
    except: pass
    return "Link Invalid", 403

@core_bp.route('/logout')
def logout(): session.clear(); return redirect('/core')

# =======================
# 🤖 机器人逻辑
# =======================

async def record_group(update: Update):
    chat = update.effective_chat
    if not chat: return None
    
    if chat.type in ['group', 'supergroup', 'channel']:
        from app import create_app
        with create_app().app_context():
            bg = BotGroup.query.filter_by(chat_id=str(chat.id)).first()
            if not bg:
                bg = BotGroup(chat_id=str(chat.id), is_active=False)
                # 默认字段
                bg.fields_config = json.dumps(DEFAULT_FIELDS, ensure_ascii=False)
                db.session.add(bg)
            
            if bg.title != (chat.title or chat.username):
                bg.title = chat.title or chat.username
                
            bg.updated_at = datetime.now()
            db.session.commit()
            return bg
    return None

async def bot_start(update: Update, context):
    if update.effective_chat.type == 'private' and update.effective_user.id == int(os.getenv('ADMIN_ID', 0)):
        token = jwt.encode({'uid': update.effective_user.id, 'exp': time.time()+3600}, os.getenv('SECRET_KEY'), algorithm='HS256')
        domain = os.getenv('RAILWAY_PUBLIC_DOMAIN', '').rstrip('/')
        url = f"{domain}/core/magic_login?token={token}"
        await update.message.reply_html(f"💼 <b>后台入口：</b>\n<a href='{url}'>点击进入管理</a>")

async def bot_handler(update: Update, context):
    msg = update.message or update.channel_post
    if not msg or not msg.text: return
    
    # 1. 发现群组
    group_orm = await record_group(update)
    if not group_orm or not group_orm.is_active: return

    text = msg.text.strip()
    user = update.effective_user
    conf = get_group_conf(group_orm)
    
    # 频道消息没有 user，只做发现逻辑，不回复打卡
    if not user: return 

    # 2. 自动点赞
    if conf.get('auto_like'):
        from app import create_app
        with create_app().app_context():
            exists = GroupUser.query.filter_by(group_id=group_orm.id, tg_id=user.id).first()
            if exists:
                try: await msg.set_reaction(conf.get('like_emoji', '❤️'))
                except: pass

    # 3. 打卡 (支持多指令)
    cmds = [c.strip() for c in conf.get('checkin_cmd', '打卡').split(',')]
    if text in cmds:
        if not conf.get('checkin_open'): return
        from app import create_app
        with create_app().app_context():
            u = GroupUser.query.filter_by(group_id=group_orm.id, tg_id=user.id).first()
            delay = int(conf.get('checkin_del_time', 30))
            
            if not u:
                reply = await msg.reply_html(conf.get('msg_not_registered'))
            elif u.checkin_time and u.checkin_time.date() == datetime.now().date():
                reply = await msg.reply_html(conf.get('msg_repeat_checkin'))
            else:
                u.checkin_time = datetime.now()
                u.online = True
                db.session.commit()
                reply = await msg.reply_html(conf.get('msg_checkin_success'))
            
            try: context.job_queue.run_once(lambda c: c.job.data.delete(), delay, data=msg)
            except: pass
            context.job_queue.run_once(lambda c: c.job.data.delete(), delay, data=reply)

    # 4. 查询 (支持多指令+筛选)
    q_cmds = [c.strip() for c in conf.get('query_cmd', '查询').split(',')]
    matched = next((c for c in q_cmds if text.startswith(c)), None)
    
    if matched:
        if not conf.get('query_open'): return
        kw = text[len(matched):].strip()
        
        from app import create_app
        with create_app().app_context():
            today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            base = GroupUser.query.filter(GroupUser.group_id == group_orm.id, GroupUser.checkin_time >= today, GroupUser.online == True)
            if kw: base = base.filter(GroupUser.profile_data.contains(kw))
            
            users = base.order_by(GroupUser.checkin_time.desc()).all()
            delay = int(conf.get('checkin_del_time', 30))
            
            if not users:
                txt = f"😢 暂无匹配 '{kw}' 的用户" if kw else "😢 本群今日暂无打卡"
                reply = await msg.reply_text(txt)
            else:
                header = conf.get('msg_query_header', '')
                tpl = conf.get('template', '')
                fields_map = {f['key']: f['label'] for f in get_group_fields(group_orm)}
                lines = []
                for u in users:
                    try:
                        d = json.loads(u.profile_data)
                        line = tpl.replace("{onlineEmoji}", conf.get('online_emoji',''))
                        for k, l in fields_map.items():
                            line = line.replace(f"{{{l}}}", str(d.get(k,'')))
                        lines.append(re.sub(r'\{.*?\}', '', line))
                    except: continue
                reply = await msg.reply_html(header + "\n\n".join(lines))
            
            try: context.job_queue.run_once(lambda c: c.job.data.delete(), delay, data=msg)
            except: pass
            context.job_queue.run_once(lambda c: c.job.data.delete(), delay, data=reply)

async def run_bot():
    import app 
    token = os.getenv('TOKEN')
    app_bot = Application.builder().token(token).build()
    app.global_bot = app_bot.bot
    app.global_loop = asyncio.get_running_loop()
    app_bot.add_handler(CommandHandler("start", bot_start))
    app_bot.add_handler(MessageHandler(filters.ALL, bot_handler))
    await app_bot.initialize()
    await app_bot.start()
    await app_bot.updater.start_polling()
    await asyncio.Event().wait()
