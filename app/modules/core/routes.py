from flask import Blueprint, render_template, request, redirect, session, jsonify
from app import db
from app.models import BotGroup, GroupUser, DEFAULT_FIELDS, DEFAULT_SYSTEM
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters
import os, jwt, time, json, asyncio, re
from datetime import datetime, timedelta

core_bp = Blueprint('core', __name__, url_prefix='/core', template_folder='templates')

# --- 辅助函数 ---
def get_group_conf(group):
    """获取群配置，合并默认值"""
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

# --- 网页路由 (保持不变，省略部分以节省篇幅，重点在 settings) ---

@core_bp.context_processor
def inject_context():
    data = {'all_groups': []}
    if session.get('logged_in'):
        data['all_groups'] = BotGroup.query.order_by(BotGroup.updated_at.desc()).all()
    gid = session.get('current_group_id')
    if gid:
        data['current_group'] = BotGroup.query.get(gid)
    return data

@core_bp.route('/')
def index():
    if not session.get('logged_in'): return render_template('base.html', page='login')
    return redirect('/core/select_group')

@core_bp.route('/select_group')
def page_select_group():
    if not session.get('logged_in'): return redirect('/core')
    groups = BotGroup.query.order_by(BotGroup.updated_at.desc()).all()
    return render_template('select_group.html', groups=groups)

@core_bp.route('/group/<int:gid>/dashboard')
def page_dashboard(gid):
    if not session.get('logged_in'): return redirect('/core')
    session['current_group_id'] = gid
    group = BotGroup.query.get_or_404(gid)
    user_count = GroupUser.query.filter_by(group_id=gid).count()
    online_count = GroupUser.query.filter_by(group_id=gid, online=True).count()
    return render_template('dashboard.html', page='dashboard', group=group, stats={'users': user_count, 'online': online_count})

@core_bp.route('/group/<int:gid>/users')
def page_users(gid):
    if not session.get('logged_in'): return redirect('/core')
    group = BotGroup.query.get_or_404(gid)
    q = request.args.get('q', '')
    query = GroupUser.query.filter_by(group_id=gid)
    if q: query = query.filter(GroupUser.profile_data.contains(q))
    users = query.order_by(GroupUser.id.desc()).all()
    fields = get_group_fields(group)
    return render_template('users.html', page='users', group=group, users=users, fields=fields, q=q)

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
    # 获取所有频道供选择推送
    channels = BotGroup.query.filter_by(type='channel').all()
    return render_template('settings.html', page='settings', group=group, conf=conf, fields=fields, channels=channels)

# --- API 路由 (保持不变) ---
@core_bp.route('/api/save_user', methods=['POST'])
def api_save_user():
    if not session.get('logged_in'): return jsonify({"status":"err"}), 403
    data = request.json
    gid = session.get('current_group_id')
    if not gid: return jsonify({"status":"err", "msg": "No group selected"})
    try:
        tg_id = int(data.get('tg_id'))
        user = GroupUser.query.filter_by(group_id=gid, tg_id=tg_id).first()
        if not user:
            user = GroupUser(group_id=gid, tg_id=tg_id)
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
    GroupUser.query.filter_by(id=request.json.get('id')).delete()
    db.session.commit()
    return jsonify({"status": "ok"})

@core_bp.route('/api/save_fields', methods=['POST'])
def api_save_fields():
    if not session.get('logged_in'): return jsonify({"status":"err"}), 403
    gid = session.get('current_group_id')
    group = BotGroup.query.get(gid)
    if group:
        group.fields_config = json.dumps(request.json, ensure_ascii=False)
        db.session.commit()
    return jsonify({"status": "ok"})

@core_bp.route('/api/save_settings', methods=['POST'])
def api_save_settings():
    if not session.get('logged_in'): return jsonify({"status":"err"}), 403
    gid = session.get('current_group_id')
    group = BotGroup.query.get(gid)
    if group:
        clean = {k: v for k, v in request.json.items() if v is not None}
        group.config = json.dumps(clean, ensure_ascii=False)
        db.session.commit()
    return jsonify({"status": "ok"})

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
# 🤖 机器人逻辑 (修复版)
# =======================

async def record_group(update: Update):
    chat = update.effective_chat
    if chat.type in ['group', 'supergroup', 'channel']:
        from app import create_app
        with create_app().app_context():
            bg = BotGroup.query.filter_by(chat_id=str(chat.id)).first()
            if not bg:
                bg = BotGroup(chat_id=str(chat.id), is_active=False)
                bg.fields_config = json.dumps(DEFAULT_FIELDS, ensure_ascii=False)
                db.session.add(bg)
            bg.title = chat.title or chat.username
            bg.type = chat.type
            bg.updated_at = datetime.now()
            db.session.commit()
            return bg
    return None

async def bot_start(update: Update, context):
    if update.effective_chat.type == 'private' and update.effective_user.id == int(os.getenv('ADMIN_ID', 0)):
        token = jwt.encode({'uid': update.effective_user.id, 'exp': time.time()+3600}, os.getenv('SECRET_KEY'), algorithm='HS256')
        domain = os.getenv('RAILWAY_PUBLIC_DOMAIN', '').rstrip('/')
        url = f"{domain}/core/magic_login?token={token}"
        await update.message.reply_html(f"💼 <b>后台入口：</b>\n<a href='{url}'>点击管理</a>")

async def bot_handler(update: Update, context):
    if not update.message or not update.message.text: return
    
    # 1. 识别当前群组
    # 注意：这里我们必须拿到最新的 group 对象，因为可能刚添加
    group = await record_group(update)
    # 如果群组未启用（is_active=False），直接忽略
    if not group or not group.is_active: return

    text = update.message.text.strip()
    user = update.effective_user
    
    # 2. 读取本群配置
    conf = get_group_conf(group)
    
    # 3. 自动点赞
    if conf.get('auto_like'):
        from app import create_app
        with create_app().app_context():
            # 查 GroupUser 表 (本群用户)
            if GroupUser.query.filter_by(group_id=group.id, tg_id=user.id).first():
                try: await update.message.set_reaction(conf.get('like_emoji', '❤️'))
                except: pass

    # 4. 打卡逻辑
    # 完全匹配指令
    if text == conf.get('checkin_cmd', '打卡'):
        if not conf.get('checkin_open'): return
        
        from app import create_app
        with create_app().app_context():
            u = GroupUser.query.filter_by(group_id=group.id, tg_id=user.id).first()
            delay = int(conf.get('checkin_del_time', 30))
            
            if not u:
                msg = await update.message.reply_html(conf.get('msg_not_registered'))
            elif u.checkin_time and u.checkin_time.date() == datetime.now().date():
                msg = await update.message.reply_html(conf.get('msg_repeat_checkin'))
            else:
                u.checkin_time = datetime.now()
                u.online = True
                db.session.commit()
                msg = await update.message.reply_html(conf.get('msg_checkin_success'))
            
            # 删除指令和回复
            try: context.job_queue.run_once(lambda c: c.job.data.delete(), delay, data=update.message)
            except: pass
            context.job_queue.run_once(lambda c: c.job.data.delete(), delay, data=msg)

    # 5. 查询逻辑 (支持关键词筛选)
    # 逻辑：消息以 "查询指令" 开头
    query_cmd = conf.get('query_cmd', '查询')
    if text.startswith(query_cmd):
        if not conf.get('query_open'): return
        
        # 提取关键词：例如 "查询 福田" -> keyword="福田"
        keyword = text[len(query_cmd):].strip()
        
        from app import create_app
        with create_app().app_context():
            today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            
            # 基础查询：本群 + 今日打卡 + 在线
            base_query = GroupUser.query.filter(
                GroupUser.group_id == group.id, 
                GroupUser.checkin_time >= today, 
                GroupUser.online == True
            )
            
            # 如果有关键词，筛选 profile_data
            if keyword:
                base_query = base_query.filter(GroupUser.profile_data.contains(keyword))
            
            users = base_query.order_by(GroupUser.checkin_time.desc()).all()
            delay = int(conf.get('checkin_del_time', 30)) # 使用同一个删除时间配置
            
            if not users:
                reply_txt = f"😢 今日暂无符合条件的用户" if keyword else "😢 本群今日暂无打卡"
                msg = await update.message.reply_text(reply_txt)
            else:
                header = conf.get('msg_query_header', '')
                tpl = conf.get('template', '')
                fields_map = {f['key']: f['label'] for f in get_group_fields(group)}
                
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
