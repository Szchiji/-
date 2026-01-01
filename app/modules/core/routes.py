from flask import Blueprint, render_template, request, redirect, session, jsonify
from app import db, global_bot, global_loop
# ⚠️ 注意这里：只导入 BotGroup，不要导入 Chat
from app.models import User, BotGroup, DEFAULT_FIELDS, DEFAULT_SYSTEM, DEFAULT_CHAT_SETTINGS
from app.services import get_conf, set_conf
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters
import os, jwt, time, json, asyncio, re
from datetime import datetime

core_bp = Blueprint('core', __name__, url_prefix='/core', template_folder='templates')

# --- 辅助函数 ---
def get_effective_conf(chat_id=None):
    # 1. 基础配置
    final_conf = get_conf('system', DEFAULT_SYSTEM).copy()
    # 2. 群组覆盖
    if chat_id:
        group = BotGroup.query.filter_by(chat_id=str(chat_id)).first()
        if group and group.config:
            try:
                g_conf = json.loads(group.config)
                for k, v in g_conf.items():
                    if v is not None and v != "": final_conf[k] = v
            except: pass
    return final_conf

# =======================
# 🌐 网页路由
# =======================

@core_bp.route('/')
def index():
    if not session.get('logged_in'): return render_template('base.html', page='login')
    return redirect('/core/dashboard')

@core_bp.route('/dashboard')
def page_dashboard():
    if not session.get('logged_in'): return redirect('/core')
    # 使用 BotGroup
    groups = BotGroup.query.order_by(BotGroup.updated_at.desc()).all()
    return render_template('dashboard.html', page='dashboard', groups=groups)

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

@core_bp.route('/group/<int:id>')
def page_group_setting(id):
    if not session.get('logged_in'): return redirect('/core')
    # 使用 BotGroup
    group = BotGroup.query.get_or_404(id)
    group_conf = {}
    if group.config:
        try: group_conf = json.loads(group.config)
        except: pass
    
    global_conf = get_conf('system', DEFAULT_SYSTEM)
    fields = get_conf('fields', DEFAULT_FIELDS)
    return render_template('group_setting.html', group=group, g_conf=group_conf, sys=global_conf, fields=fields)

@core_bp.route('/magic_login')
def magic_login():
    token = request.args.get('token')
    try:
        if jwt.decode(token, os.getenv('SECRET_KEY'), algorithms=['HS256']).get('uid') == int(os.getenv('ADMIN_ID', 0)):
            session['logged_in'] = True
            return redirect('/core/dashboard')
    except: pass
    return "Link Invalid", 403

@core_bp.route('/logout')
def logout(): session.clear(); return redirect('/core')


# =======================
# 📡 API
# =======================

@core_bp.route('/api/toggle_group', methods=['POST'])
def api_toggle_group():
    if not session.get('logged_in'): return jsonify({"status":"err"}), 403
    gid = request.json.get('id')
    active = request.json.get('active')
    # 使用 BotGroup
    group = BotGroup.query.get(gid)
    if group:
        group.is_active = active
        db.session.commit()
    return jsonify({"status": "ok"})

@core_bp.route('/api/save_group_config', methods=['POST'])
def api_save_group_config():
    if not session.get('logged_in'): return jsonify({"status":"err"}), 403
    gid = request.json.get('id')
    config_data = request.json.get('config')
    # 使用 BotGroup
    group = BotGroup.query.get(gid)
    if group:
        clean_conf = {k: v for k, v in config_data.items() if v is not None}
        group.config = json.dumps(clean_conf, ensure_ascii=False)
        db.session.commit()
    return jsonify({"status": "ok"})

@core_bp.route('/api/save_user', methods=['POST'])
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


# =======================
# 🤖 机器人逻辑
# =======================

async def record_group(update: Update):
    chat = update.effective_chat
    if chat.type in ['group', 'supergroup', 'channel']:
        from app import create_app
        with create_app().app_context():
            # 使用 BotGroup
            bg = BotGroup.query.filter_by(chat_id=str(chat.id)).first()
            if not bg:
                bg = BotGroup(chat_id=str(chat.id), is_active=False)
                db.session.add(bg)
            bg.title = chat.title or chat.username
            bg.type = chat.type
            bg.updated_at = datetime.now()
            db.session.commit()
            return bg.is_active
    return True

async def bot_start(update: Update, context):
    if update.effective_chat.type == 'private' and update.effective_user.id == int(os.getenv('ADMIN_ID', 0)):
        token = jwt.encode({'uid': update.effective_user.id, 'exp': time.time()+3600}, os.getenv('SECRET_KEY'), algorithm='HS256')
        domain = os.getenv('RAILWAY_PUBLIC_DOMAIN', '').rstrip('/')
        url = f"{domain}/core/magic_login?token={token}"
        await update.message.reply_html(f"💼 <b>管理后台：</b>\n<a href='{url}'>点击进入</a>")

async def bot_handler(update: Update, context):
    if not update.message or not update.message.text: return
    
    is_active = await record_group(update)
    if not is_active: return

    text = update.message.text.strip()
    user = update.effective_user
    chat_id = update.effective_chat.id
    
    # 获取配置
    conf = get_effective_conf(chat_id)

    # 自动点赞
    if conf.get('auto_like'):
        from app import create_app
        with create_app().app_context():
            if User.query.filter_by(tg_id=user.id).first():
                try: await update.message.set_reaction(conf.get('like_emoji', '❤️'))
                except: pass

    # 打卡
    if text == conf.get('checkin_cmd', '打卡'):
        if not conf.get('checkin_open'): return
        from app import create_app
        with create_app().app_context():
            u = User.query.filter_by(tg_id=user.id).first()
            delay = int(conf.get('checkin_del_time', 30))
            
            if not u:
                msg = await update.message.reply_html(conf.get('msg_not_registered'))
            elif u.checkin_time and u.checkin_time.date() == datetime.now().date():
                msg = await update.message.reply_html(conf.get('msg_repeat_checkin'))
            else:
                u.checkin_time = datetime.now()
                u.online = True
                u.last_chat_id = str(chat_id)
                db.session.commit()
                msg = await update.message.reply_html(conf.get('msg_checkin_success'))
            
            try: context.job_queue.run_once(lambda c: c.job.data.delete(), delay, data=update.message)
            except: pass
            context.job_queue.run_once(lambda c: c.job.data.delete(), delay, data=msg)

    # 查询
    if text == conf.get('query_cmd', '查询'):
        if not conf.get('query_open'): return
        from app import create_app
        with create_app().app_context():
            today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            users = User.query.filter(User.checkin_time >= today, User.online == True).all()
            delay = int(conf.get('query_del_time', 30))
            
            if not users:
                msg = await update.message.reply_text("😢 今日暂无打卡")
            else:
                header = conf.get('msg_query_header', '')
                tpl = conf.get('template', '')
                fields_map = {f['key']: f['label'] for f in get_conf('fields', DEFAULT_FIELDS)}
                lines = []
                for u in users:
                    try:
                        d = json.loads(u.profile_data)
                        line = tpl.replace("{onlineEmoji}", conf.get('online_emoji',''))
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
    app_bot = Application.builder().token(token).build()
    app.global_bot = app_bot.bot
    app.global_loop = asyncio.get_running_loop()
    app_bot.add_handler(CommandHandler("start", bot_start))
    app_bot.add_handler(MessageHandler(filters.ALL, bot_handler))
    await app_bot.initialize()
    await app_bot.start()
    await app_bot.updater.start_polling()
    await asyncio.Event().wait()
