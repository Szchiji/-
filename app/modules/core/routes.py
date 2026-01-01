from flask import Blueprint, render_template, request, redirect, session, jsonify
from app import db
from app.models import BotGroup, GroupUser, DEFAULT_FIELDS, DEFAULT_SYSTEM
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters
import os, jwt, time, json, asyncio, re
from datetime import datetime, timedelta

core_bp = Blueprint('core', __name__, url_prefix='/core', template_folder='templates')

# --- 上下文处理器 (修复侧边栏) ---
@core_bp.context_processor
def inject_global_data():
    if not session.get('logged_in'): return {}
    data = {
        'all_groups': BotGroup.query.order_by(BotGroup.updated_at.desc()).all(),
        'current_group': None
    }
    # 尝试从 URL 参数或 Session 获取当前群组
    gid = request.view_args.get('gid') if request.view_args else None
    if gid:
        data['current_group'] = BotGroup.query.get(gid)
        session['current_group_id'] = gid # 刷新 session
    elif session.get('current_group_id'):
        data['current_group'] = BotGroup.query.get(session['current_group_id'])
    
    return data

def get_group_conf(group):
    conf = DEFAULT_SYSTEM.copy()
    if group and group.config:
        try:
            c = json.loads(group.config)
            for k, v in c.items():
                if v is not None: conf[k] = v
        except: pass
    return conf

def get_group_fields(group):
    if group and group.fields_config:
        try: return json.loads(group.fields_config)
        except: pass
    return DEFAULT_FIELDS

# --- 网页路由 ---

@core_bp.route('/')
def index():
    return redirect('/core/select_group') if session.get('logged_in') else render_template('base.html', page='login')

@core_bp.route('/select_group')
def page_select_group():
    if not session.get('logged_in'): return redirect('/core')
    session.pop('current_group_id', None) # 清除当前群组状态
    groups = BotGroup.query.order_by(BotGroup.updated_at.desc()).all()
    return render_template('select_group.html', groups=groups)

@core_bp.route('/group/<int:gid>/dashboard')
def page_dashboard(gid):
    if not session.get('logged_in'): return redirect('/core')
    group = BotGroup.query.get_or_404(gid)
    users = GroupUser.query.filter_by(group_id=gid).count()
    online = GroupUser.query.filter_by(group_id=gid, online=True).count()
    return render_template('dashboard.html', page='dashboard', group=group, stats={'users': users, 'online': online})

@core_bp.route('/group/<int:gid>/users')
def page_users(gid):
    if not session.get('logged_in'): return redirect('/core')
    group = BotGroup.query.get_or_404(gid)
    users = GroupUser.query.filter_by(group_id=gid).order_by(GroupUser.id.desc()).all()
    fields = get_group_fields(group)
    return render_template('users.html', page='users', group=group, users=users, fields=fields)

@core_bp.route('/group/<int:gid>/fields')
def page_fields(gid):
    if not session.get('logged_in'): return redirect('/core')
    group = BotGroup.query.get_or_404(gid)
    fields = get_group_fields(group)
    return render_template('fields.html', page='fields', group=group, fields=fields, fields_json=json.dumps(fields))

@core_bp.route('/group/<int:gid>/settings')
def page_settings(gid):
    if not session.get('logged_in'): return redirect('/core')
    group = BotGroup.query.get_or_404(gid)
    conf = get_group_conf(group)
    fields = get_group_fields(group)
    return render_template('settings.html', page='settings', group=group, conf=conf, fields=fields)

@core_bp.route('/magic_login')
def magic_login():
    token = request.args.get('token')
    try:
        if jwt.decode(token, os.getenv('SECRET_KEY'), algorithms=['HS256']).get('uid') == int(os.getenv('ADMIN_ID', 0)):
            session['logged_in'] = True
            return redirect('/core/select_group')
    except: pass
    return "Link Invalid", 403

# --- API (修复保存问题) ---

@core_bp.route('/api/save_user', methods=['POST'])
def api_save_user():
    if not session.get('logged_in'): return jsonify({"status":"err"}), 403
    # 强制前端传 group_id
    gid = request.json.get('group_id')
    if not gid: return jsonify({"status":"err", "msg": "Missing group_id"})
    
    try:
        tg_id = int(request.json.get('tg_id'))
        user = GroupUser.query.filter_by(group_id=gid, tg_id=tg_id).first()
        if not user:
            user = GroupUser(group_id=gid, tg_id=tg_id)
            db.session.add(user)
        user.profile_data = json.dumps(request.json.get('profile', {}), ensure_ascii=False)
        days = int(request.json.get('add_days', 0))
        if days:
            now = datetime.now()
            base = user.expiration_date if (user.expiration_date and user.expiration_date > now) else now
            user.expiration_date = base + timedelta(days=days)
        db.session.commit()
        return jsonify({"status": "ok"})
    except Exception as e: 
        db.session.rollback()
        return jsonify({"status": "err", "msg": str(e)})

@core_bp.route('/api/save_settings', methods=['POST'])
def api_save_settings():
    if not session.get('logged_in'): return jsonify({"status":"err"}), 403
    gid = request.json.get('group_id') # 强制前端传 ID
    group = BotGroup.query.get(gid)
    if group:
        # 合并旧配置，防止字段丢失
        old_conf = get_group_conf(group)
        new_conf = request.json.get('config', {})
        old_conf.update(new_conf) # 更新覆盖
        
        group.config = json.dumps(old_conf, ensure_ascii=False)
        db.session.commit()
        return jsonify({"status": "ok"})
    return jsonify({"status": "err", "msg": "Group not found"})

@core_bp.route('/api/toggle_group', methods=['POST'])
def api_toggle_group():
    if not session.get('logged_in'): return jsonify({"status":"err"}), 403
    group = BotGroup.query.get(request.json.get('id'))
    if group:
        group.is_active = request.json.get('active')
        db.session.commit()
    return jsonify({"status": "ok"})

# --- 机器人逻辑 ---

async def bot_handler(update: Update, context):
    msg = update.message or update.channel_post
    if not msg: return
    
    chat = update.effective_chat
    # 1. 自动发现逻辑
    if chat.type in ['group', 'supergroup', 'channel']:
        from app import create_app
        with create_app().app_context():
            group = BotGroup.query.filter_by(chat_id=str(chat.id)).first()
            if not group:
                group = BotGroup(chat_id=str(chat.id), title=chat.title, type=chat.type, is_active=False)
                # 默认字段
                group.fields_config = json.dumps(DEFAULT_FIELDS, ensure_ascii=False)
                db.session.add(group)
                db.session.commit()
            
            if not group.is_active or not msg.text: return

            # 2. 业务逻辑
            conf = get_group_conf(group)
            text = msg.text.strip()
            user = update.effective_user

            # 自动点赞
            if user and conf.get('auto_like'):
                if GroupUser.query.filter_by(group_id=group.id, tg_id=user.id).first():
                    try: await msg.set_reaction(conf.get('like_emoji', '❤️'))
                    except: pass

            # 打卡
            if user and text == conf.get('checkin_cmd', '打卡'):
                if not conf.get('checkin_open'): return
                u = GroupUser.query.filter_by(group_id=group.id, tg_id=user.id).first()
                if not u:
                    reply = await msg.reply_html(conf.get('msg_not_registered'))
                elif u.checkin_time and u.checkin_time.date() == datetime.now().date():
                    reply = await msg.reply_html(conf.get('msg_repeat_checkin'))
                else:
                    u.checkin_time = datetime.now()
                    u.online = True
                    db.session.commit()
                    reply = await msg.reply_html(conf.get('msg_checkin_success'))
                
                try: context.job_queue.run_once(lambda c: c.job.data.delete(), int(conf.get('del_time', 30)), data=msg)
                except: pass
                context.job_queue.run_once(lambda c: c.job.data.delete(), int(conf.get('del_time', 30)), data=reply)

            # 查询 (支持多指令分割，例如用逗号或空格)
            query_cmds = conf.get('query_cmd', '查询').split() # 简单空格分割，暂不支持复杂配置
            # 简单实现：只要开头匹配任意一个指令
            is_query = False
            filter_kw = ""
            
            for cmd in query_cmds:
                if text.startswith(cmd):
                    is_query = True
                    filter_kw = text[len(cmd):].strip()
                    break
            
            if is_query and conf.get('query_open'):
                today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                base_q = GroupUser.query.filter(GroupUser.group_id == group.id, GroupUser.checkin_time >= today, GroupUser.online == True)
                if filter_kw: base_q = base_q.filter(GroupUser.profile_data.contains(filter_kw))
                
                users = base_q.all()
                if not users:
                    reply = await msg.reply_text(f"😢 暂无{'符合条件的' if filter_kw else ''}打卡记录")
                else:
                    header = conf.get('msg_query_header', '')
                    tpl = conf.get('template', '')
                    fields_map = {f['key']: f['label'] for f in get_group_fields(group)}
                    lines = []
                    for u in users:
                        try:
                            d = json.loads(u.profile_data)
                            l = tpl.replace("{onlineEmoji}", conf.get('online_emoji',''))
                            for k, lbl in fields_map.items(): l = l.replace(f"{{{lbl}}}", str(d.get(k,'')))
                            lines.append(re.sub(r'\{.*?\}', '', l))
                        except: continue
                    reply = await msg.reply_html(header + "\n\n".join(lines))
                
                try: context.job_queue.run_once(lambda c: c.job.data.delete(), int(conf.get('del_time', 30)), data=msg)
                except: pass
                context.job_queue.run_once(lambda c: c.job.data.delete(), int(conf.get('del_time', 30)), data=reply)

async def bot_start(update: Update, context):
    if update.effective_chat.type == 'private' and update.effective_user.id == int(os.getenv('ADMIN_ID', 0)):
        token = jwt.encode({'uid': update.effective_user.id, 'exp': time.time()+3600}, os.getenv('SECRET_KEY'), algorithm='HS256')
        url = f"{os.getenv('RAILWAY_PUBLIC_DOMAIN','').rstrip('/')}/core/magic_login?token={token}"
        await update.message.reply_html(f"💼 <b>后台入口：</b>\n<a href='{url}'>点击进入</a>")

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
