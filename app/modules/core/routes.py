from flask import Blueprint, render_template, request, redirect, session, jsonify, g
from app import db
from app.models import BotGroup, GroupUser, DEFAULT_FIELDS, DEFAULT_SYSTEM
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters
import os, jwt, time, json, asyncio, re
from datetime import datetime, timedelta

core_bp = Blueprint('core', __name__, url_prefix='/core', template_folder='templates')

# --- 上下文 & 辅助 ---
@core_bp.context_processor
def inject_context():
    data = {'all_groups': []}
    if session.get('logged_in'):
        data['all_groups'] = BotGroup.query.order_by(BotGroup.updated_at.desc()).all()
    gid = session.get('current_group_id')
    if gid: data['current_group'] = BotGroup.query.get(gid)
    return data

def safe_int(val, default=30):
    try: return int(val) if val and str(val).strip() else default
    except: return default

def get_group_conf(group):
    conf = DEFAULT_SYSTEM.copy()
    if group and group.config:
        try:
            c = json.loads(group.config)
            if 'config' in c and isinstance(c['config'], dict): c = c['config']
            for k, v in c.items():
                if v is not None: conf[k] = v
        except: pass
    return conf

def get_group_fields(group):
    if group and group.fields_config:
        try: return json.loads(group.fields_config)
        except: pass
    return DEFAULT_FIELDS

# =======================
# 🌐 网页路由 (保持不变)
# =======================
@core_bp.route('/')
def index(): return redirect('/core/select_group') if session.get('logged_in') else render_template('base.html', page='login')

@core_bp.route('/select_group')
def page_select_group():
    if not session.get('logged_in'): return redirect('/core')
    session.pop('current_group_id', None)
    groups = BotGroup.query.order_by(BotGroup.updated_at.desc()).all()
    return render_template('select_group.html', groups=groups)

@core_bp.route('/group/<int:gid>/dashboard')
def page_dashboard(gid):
    if not session.get('logged_in'): return redirect('/core')
    session['current_group_id'] = gid
    group = BotGroup.query.get_or_404(gid)
    stats = {'users': GroupUser.query.filter_by(group_id=gid).count(), 'online': GroupUser.query.filter_by(group_id=gid, online=True).count()}
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
    return render_template('settings.html', page='settings', group=group, conf=conf, fields=fields)

# =======================
# 📡 API 路由
# =======================
@core_bp.route('/api/save_settings', methods=['POST'])
def api_save_settings():
    if not session.get('logged_in'): return jsonify({"status":"err"}), 403
    req = request.json
    gid = req.get('group_id') or session.get('current_group_id')
    group = BotGroup.query.get(gid)
    if group:
        real = req.get('config', req)
        if 'group_id' in real: del real['group_id']
        group.config = json.dumps({k:v for k,v in real.items() if v is not None}, ensure_ascii=False)
        db.session.commit()
    return jsonify({"status": "ok"})

@core_bp.route('/api/save_fields', methods=['POST'])
def api_save_fields():
    if not session.get('logged_in'): return jsonify({"status":"err"}), 403
    gid = session.get('current_group_id')
    group = BotGroup.query.get(gid)
    if group:
        d = request.json
        group.fields_config = json.dumps(d.get('fields', d), ensure_ascii=False)
        db.session.commit()
    return jsonify({"status": "ok"})

@core_bp.route('/api/save_user', methods=['POST'])
def api_save_user():
    if not session.get('logged_in'): return jsonify({"status":"err"}), 403
    d = request.json
    gid = d.get('group_id') or session.get('current_group_id')
    try:
        tg_id = int(d.get('tg_id'))
        user = GroupUser.query.filter_by(group_id=gid, tg_id=tg_id).first()
        if not user:
            user = GroupUser(group_id=gid, tg_id=tg_id)
            db.session.add(user)
        user.profile_data = json.dumps(d.get('profile', {}), ensure_ascii=False)
        days = int(d.get('add_days', 0))
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
    GroupUser.query.filter_by(id=request.json.get('id')).delete()
    db.session.commit()
    return jsonify({"status": "ok"})

@core_bp.route('/api/push_user', methods=['POST'])
def api_push_user():
    if not session.get('logged_in'): return jsonify({"status":"err"}), 403
    import app
    gid = session.get('current_group_id')
    group = BotGroup.query.get(gid)
    user = GroupUser.query.get(request.json.get('id'))
    conf = get_group_conf(group)
    
    cid = conf.get('push_channel_id')
    if not cid: return jsonify({"status": "err", "msg": "未配置推送频道ID"})
    
    tpl = conf.get('push_template', '')
    f_map = {f['key']: f['label'] for f in get_group_fields(group)}
    try:
        d = json.loads(user.profile_data)
        line = tpl.replace("{onlineEmoji}", conf.get('online_emoji',''))
        for k, l in f_map.items(): line = line.replace(f"{{{l}}}", str(d.get(k,'')))
        line = line.replace("{tg_id}", str(user.tg_id))
        line = re.sub(r'\{.*?\}', '', line)
        
        if app.global_bot and app.global_loop:
            asyncio.run_coroutine_threadsafe(
                app.global_bot.send_message(chat_id=cid, text=line, parse_mode='HTML'),
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

async def get_group_info_safe(chat):
    if chat.type not in ['group', 'supergroup', 'channel']: return None
    from app import create_app
    with create_app().app_context():
        bg = BotGroup.query.filter_by(chat_id=str(chat.id)).first()
        if not bg:
            bg = BotGroup(chat_id=str(chat.id), is_active=True, type=chat.type, title=chat.title or "Channel")
            bg.fields_config = json.dumps(DEFAULT_FIELDS, ensure_ascii=False)
            db.session.add(bg)
        if bg.title != (chat.title or chat.username):
            bg.title = chat.title or chat.username
        bg.updated_at = datetime.now()
        db.session.commit()
        return {'id': bg.id, 'is_active': bg.is_active, 'config': bg.config, 'fields_config': bg.fields_config}

async def bot_start(update: Update, context):
    if update.effective_chat.type == 'private' and update.effective_user.id == int(os.getenv('ADMIN_ID', 0)):
        token = jwt.encode({'uid': update.effective_user.id, 'exp': time.time()+3600}, os.getenv('SECRET_KEY'), algorithm='HS256')
        url = f"{os.getenv('RAILWAY_PUBLIC_DOMAIN', '').rstrip('/')}/core/magic_login?token={token}"
        await update.message.reply_html(f"💼 <b>后台入口：</b>\n<a href='{url}'>点击管理</a>")

async def bot_handler(update: Update, context):
    msg = update.message or update.channel_post
    if not msg: return
    
    g_info = await get_group_info_safe(update.effective_chat)
    if not g_info: return

    class Mock:
        def __init__(self, c, f): self.config=c; self.fields_config=f
    mock_g = Mock(g_info['config'], g_info['fields_config'])
    conf = get_group_conf(mock_g)
    
    if not update.effective_user: return # 频道消息不处理

    text = msg.text.strip() if msg.text else ""
    user_id = update.effective_user.id
    gid = g_info['id']

    # 1. 自动点赞 (强转类型对比)
    if conf.get('auto_like'):
        from app import create_app
        with create_app().app_context():
            # 必须用 int() 确保类型一致
            uid = db.session.query(GroupUser.id).filter_by(group_id=gid, tg_id=int(user_id)).scalar()
            if uid:
                try: await msg.set_reaction(conf.get('like_emoji', '❤️'))
                except: pass

    # 2. 打卡
    cmds = [c.strip() for c in conf.get('checkin_cmd', '打卡').split(',')]
    if text in cmds:
        if not conf.get('checkin_open'): return
        from app import create_app
        with create_app().app_context():
            u = GroupUser.query.filter_by(group_id=gid, tg_id=int(user_id)).first()
            delay = safe_int(conf.get('checkin_del_time'), 30)
            
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
            return

    # 3. 查询 (高级筛选)
    q_cmds = [c.strip() for c in conf.get('query_cmd', '查询').split(',')]
    matched_cmd = next((c for c in q_cmds if text.startswith(c)), None)
    
    if matched_cmd:
        if not conf.get('query_open'): return
        # 提取参数： "查询 福田" -> "福田"
        filter_kw = text[len(matched_cmd):].strip()
        
        from app import create_app
        with create_app().app_context():
            today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            base = GroupUser.query.filter(GroupUser.group_id == gid, GroupUser.checkin_time >= today, GroupUser.online == True)
            
            # 如果有参数，就筛选 profile_data
            if filter_kw: base = base.filter(GroupUser.profile_data.contains(filter_kw))
            
            users = base.order_by(GroupUser.checkin_time.desc()).all()
            delay = safe_int(conf.get('checkin_del_time'), 30)
            
            if not users:
                txt = f"😢 暂无匹配 '{filter_kw}' 的用户" if filter_kw else "😢 本群今日暂无打卡"
                reply = await msg.reply_text(txt)
            else:
                header = conf.get('msg_query_header', '')
                tpl = conf.get('template', '')
                f_map = {f['key']: f['label'] for f in get_group_fields(mock_g)}
                lines = []
                for u in users:
                    try:
                        d = json.loads(u.profile_data)
                        l = tpl.replace("{onlineEmoji}", conf.get('online_emoji',''))
                        for k, lbl in f_map.items(): l = l.replace(f"{{{lbl}}}", str(d.get(k,'')))
                        lines.append(re.sub(r'\{.*?\}', '', l))
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
