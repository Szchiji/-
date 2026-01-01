from flask import Blueprint, render_template, request, redirect, session, jsonify
from app import db
from app.models import BotGroup, GroupUser, DEFAULT_FIELDS, DEFAULT_SYSTEM
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ChatMemberHandler, filters
import os, jwt, time, json, asyncio, re, requests, math
from datetime import datetime, timedelta

core_bp = Blueprint('core', __name__, url_prefix='/core', template_folder='templates')

# --- Context ---
@core_bp.context_processor
def inject_context():
    data = {'all_groups': []}
    if session.get('logged_in'):
        data['all_groups'] = BotGroup.query.order_by(BotGroup.updated_at.desc()).all()
    gid = session.get('current_group_id')
    if gid: data['current_group'] = BotGroup.query.get(gid)
    return data

def safe_int(val, default=30):
    try: return int(val) if str(val).strip() else default
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

# --- Web Routes (保持不变) ---
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

# --- APIs (保持不变) ---
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
        u = GroupUser.query.filter_by(group_id=gid, tg_id=tg_id).first()
        if not u:
            u = GroupUser(group_id=gid, tg_id=tg_id)
            db.session.add(u)
        u.profile_data = json.dumps(d.get('profile', {}), ensure_ascii=False)
        days = int(d.get('add_days', 0))
        if days:
            now = datetime.now()
            base = u.expiration_date if (u.expiration_date and u.expiration_date > now) else now
            u.expiration_date = base + timedelta(days=days)
            u.is_banned = False 
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
    gid = session.get('current_group_id')
    uid = request.json.get('id')
    group = BotGroup.query.get(gid)
    user = GroupUser.query.get(uid)
    conf = get_group_conf(group)
    cid = conf.get('push_channel_id')
    if not cid: return jsonify({"status": "err", "msg": "未配置推送频道ID"})
    try:
        final_cid = str(cid).strip()
        if not final_cid.startswith('-100'): final_cid = "-100" + final_cid.replace("-", "")
        tpl = conf.get('push_template', '')
        f_map = {f['key']: f['label'] for f in get_group_fields(group)}
        d = json.loads(user.profile_data)
        line = tpl.replace("{onlineEmoji}", conf.get('online_emoji',''))
        for k, l in f_map.items(): line = line.replace(f"{{{l}}}", str(d.get(k,'')))
        line = line.replace("{tg_id}", str(user.tg_id))
        line = re.sub(r'\{.*?\}', '', line)
        token = os.getenv('TOKEN')
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": final_cid, "text": line, "parse_mode": "HTML"}, timeout=2)
        return jsonify({"status": "ok", "msg": "✅ 推送成功"})
    except Exception as e: return jsonify({"status": "err", "msg": str(e)})

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
# 🤖 机器人逻辑 (绝杀优化版)
# =======================

# 全局 HTTP Session 提高并发性能
http = requests.Session()

def do_like(chat_id, message_id, emoji):
    """强力点赞：使用 Session 和更长的超时时间"""
    token = os.getenv('TOKEN')
    url = f"https://api.telegram.org/bot{token}/setMessageReaction"
    try:
        http.post(url, json={
            "chat_id": chat_id, 
            "message_id": message_id, 
            "reaction": [{"type": "emoji", "emoji": emoji}]
        }, timeout=(3.05, 5)) # 连接3秒，读取5秒
    except Exception as e:
        print(f"[Like Fail] {e}")

async def check_expiration_and_mute(context, group_id, user_id, chat_id, conf):
    from app import create_app
    with create_app().app_context():
        u = GroupUser.query.filter_by(group_id=group_id, tg_id=int(user_id)).first()
        if not u or not u.expiration_date: return
        
        now = datetime.now()
        # 过期禁言
        if u.expiration_date < now and not u.is_banned:
            try: 
                await context.bot.restrict_chat_member(chat_id=chat_id, user_id=user_id, permissions=ChatPermissions(can_send_messages=False))
                u.is_banned = True
                db.session.commit()
                await context.bot.send_message(chat_id=chat_id, text=conf.get('msg_expired_ban', '⛔️ 过期禁言'), parse_mode='HTML')
                return True
            except: pass
        # 续费解禁
        elif u.expiration_date > now and u.is_banned:
            try:
                await context.bot.restrict_chat_member(chat_id=chat_id, user_id=user_id, 
                    permissions=ChatPermissions(can_send_messages=True, can_send_media_messages=True, can_send_other_messages=True))
                u.is_banned = False
                db.session.commit()
            except: pass
    return False

def build_list_text(users, page, per_page, conf, fields, header):
    start = (page - 1) * per_page
    current_users = users[start:start+per_page]
    tpl = conf.get('template', '{昵称} | {地区}')
    f_map = {f['key']: f['label'] for f in fields}
    lines = []
    for idx, u in enumerate(current_users):
        try:
            d = json.loads(u.profile_data)
            l = tpl.replace("{onlineEmoji}", conf.get('online_emoji',''))
            for k, lbl in f_map.items(): l = l.replace(f"{{{lbl}}}", str(d.get(k,'')))
            l = l.replace("{序号}", str(start + idx + 1))
            lines.append(re.sub(r'\{.*?\}', '', l))
        except: continue
    return header + "\n\n" + "\n".join(lines)

def get_pagination_markup(page, total_pages, kw, conf):
    buttons = []
    nav_row = []
    safe_kw = kw if kw else "None"
    
    # 翻页按钮携带页码和关键词
    if page > 1: nav_row.append(InlineKeyboardButton("⬅️ 上页", callback_data=f"pg|{page-1}|{safe_kw}"))
    nav_row.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
    if page < total_pages: nav_row.append(InlineKeyboardButton("下页 ➡️", callback_data=f"pg|{page+1}|{safe_kw}"))
    if nav_row: buttons.append(nav_row)
    
    custom_btns = conf.get('custom_buttons', '')
    if custom_btns:
        try:
            for btn in json.loads(custom_btns):
                if btn.get('text') and btn.get('url'):
                    buttons.append([InlineKeyboardButton(btn['text'], url=btn['url'])])
        except: pass
    return InlineKeyboardMarkup(buttons)

async def do_query_page(chat_id, group_id, conf, fields, kw=None, page=1):
    from app import create_app
    with create_app().app_context():
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        base = GroupUser.query.filter(GroupUser.group_id == group_id, GroupUser.checkin_time >= today, GroupUser.online == True)
        if kw: base = base.filter(GroupUser.profile_data.contains(kw))
        
        page_size = safe_int(conf.get('page_size'), 10)
        total_pages = math.ceil(base.count() / page_size) or 1
        if page > total_pages: page = total_pages
        if page < 1: page = 1
        
        users = base.order_by(GroupUser.checkin_time.desc()).limit(page_size).offset((page-1)*page_size).all()
        header = conf.get('msg_filter_header', '🔍 <b>筛选结果：</b>') if kw else conf.get('msg_query_header', '🔍 <b>今日在线：</b>')
        
        if not users:
            text = f"😢 没找到 '{kw}' 的相关用户" if kw else "😢 今日暂无打卡"
            markup = None
        else:
            text = build_list_text(users, page, page_size, conf, fields, header)
            markup = get_pagination_markup(page, total_pages, kw, conf)
            
        return text, markup, users

async def bot_handler(update: Update, context):
    msg = update.message or update.channel_post
    if not msg: return
    if msg.chat.type not in ['group', 'supergroup', 'channel']: return
    
    g_info = await get_group_info_safe(update.effective_chat)
    if not g_info or not g_info['is_active']: return

    class Mock:
        def __init__(self, c, f): self.config=c; self.fields_config=f
    mock_g = Mock(g_info['config'], g_info['fields_config'])
    conf = get_group_conf(mock_g)
    fields = get_group_fields(mock_g)
    
    if not update.effective_user: return
    user = update.effective_user
    text = msg.text.strip() if msg.text else ""
    gid = g_info['id']

    # 1. 点赞与权限
    from app import create_app
    with create_app().app_context():
        exists = db.session.query(GroupUser.id).filter_by(group_id=gid, tg_id=user.id).scalar()
        if exists:
            if conf.get('auto_mute_expired'):
                if await check_expiration_and_mute(context, gid, user.id, msg.chat.id, conf): return
            if conf.get('auto_like'):
                do_like(msg.chat.id, msg.message_id, conf.get('like_emoji', '❤️'))

    # 2. 打卡
    checkin_cmds = [c.strip() for c in conf.get('checkin_cmd', '打卡').split(',')]
    if text in checkin_cmds:
        if not conf.get('checkin_open'): return
        with create_app().app_context():
            u = GroupUser.query.filter_by(group_id=gid, tg_id=int(user.id)).first()
            if not u: r = await msg.reply_html(conf.get('msg_not_registered'))
            elif u.checkin_time and u.checkin_time.date() == datetime.now().date(): r = await msg.reply_html(conf.get('msg_repeat_checkin'))
            else:
                u.checkin_time = datetime.now()
                u.online = True
                db.session.commit()
                r = await msg.reply_html(conf.get('msg_checkin_success'))
            
            delay = safe_int(conf.get('checkin_del_time'), 30)
            context.job_queue.run_once(lambda c: c.job.data.delete(), delay, data=r)
            return

    # 3. 独立查询逻辑 (取消互斥删除，实现多人独立查询)
    is_normal_query = conf.get('query_open') and text in [c.strip() for c in conf.get('query_cmd', '查询').split(',')]
    
    is_filter_query = False
    kw = None
    if conf.get('query_filter_open'):
        # 1. 显式筛选: "查询 福田"
        q_cmds = [c.strip() for c in conf.get('query_cmd', '查询').split(',')]
        matched = next((c for c in q_cmds if text.startswith(c + " ")), None)
        if matched:
            kw = text[len(matched):].strip()
            is_filter_query = True
        # 2. 隐式筛选: "福田" (非指令，短文本)
        elif len(text) < 10 and not text.startswith('/'):
            kw = text
            is_filter_query = True

    if is_normal_query or is_filter_query:
        if is_filter_query and not kw: return 
        
        text_resp, markup, users = await do_query_page(msg.chat.id, gid, conf, fields, kw, 1)
        
        if is_filter_query and not users: return 
        
        # ⚠️ 关键修改：每条消息都是独立的，互不影响
        # 禁用链接预览，防止刷屏
        sent = await msg.reply_html(text_resp, reply_markup=markup, disable_web_page_preview=True)
        
        # 仍然保持自动删除机制，防止消息堆积太多
        del_time = safe_int(conf.get('query_del_time'), 60)
        context.job_queue.run_once(lambda c: c.job.data.delete(), del_time, data=sent)

# --- 翻页回调 (独立更新) ---
async def pagination_callback(update: Update, context):
    query = update.callback_query
    if query.data == "noop": return await query.answer()
    parts = query.data.split('|')
    page = int(parts[1])
    kw = parts[2] if parts[2] != "None" else None
    
    g_info = await get_group_info_safe(update.effective_chat)
    if not g_info: return await query.answer("过期")
    
    class Mock:
        def __init__(self, c, f): self.config=c; self.fields_config=f
    mock_g = Mock(g_info['config'], g_info['fields_config'])
    conf = get_group_conf(mock_g)
    fields = get_group_fields(mock_g)
    
    text, markup, _ = await do_query_page(update.effective_chat.id, g_info['id'], conf, fields, kw, page)
    
    # ⚠️ 只编辑当前这条消息，不影响其他人的消息
    try: 
        await query.edit_message_text(text=text, parse_mode='HTML', reply_markup=markup, disable_web_page_preview=True)
        await query.answer()
    except: await query.answer()

async def get_group_info_safe(chat):
    if chat.type not in ['group', 'supergroup', 'channel']: return None
    from app import create_app
    with create_app().app_context():
        bg = BotGroup.query.filter_by(chat_id=str(chat.id)).first()
        if not bg:
            bg = BotGroup(chat_id=str(chat.id), is_active=True, type=chat.type, title=chat.title)
            bg.fields_config = json.dumps(DEFAULT_FIELDS, ensure_ascii=False)
            db.session.add(bg)
            db.session.commit()
        return {'id': bg.id, 'is_active': bg.is_active, 'config': bg.config, 'fields_config': bg.fields_config}

async def bot_start(update: Update, context):
    if update.effective_chat.type == 'private' and update.effective_user.id == int(os.getenv('ADMIN_ID', 0)):
        token = jwt.encode({'uid': update.effective_user.id, 'exp': time.time()+3600}, os.getenv('SECRET_KEY'), algorithm='HS256')
        url = f"{os.getenv('RAILWAY_PUBLIC_DOMAIN', '').rstrip('/')}/core/magic_login?token={token}"
        await update.message.reply_html(f"💼 <b>后台入口：</b>\n<a href='{url}'>点击管理</a>")

async def chat_member_handler(update: Update, context): await get_group_info_safe(update.effective_chat)

async def run_bot():
    import app 
    token = os.getenv('TOKEN')
    app_bot = Application.builder().token(token).build()
    app.global_bot = app_bot.bot
    app.global_loop = asyncio.get_running_loop()
    app_bot.add_handler(CommandHandler("start", bot_start))
    app_bot.add_handler(CallbackQueryHandler(pagination_callback))
    app_bot.add_handler(ChatMemberHandler(chat_member_handler, ChatMemberHandler.MY_CHAT_MEMBER))
    app_bot.add_handler(MessageHandler(filters.ALL, bot_handler))
    await app_bot.initialize()
    await app_bot.start()
    await app_bot.updater.start_polling()
    await asyncio.Event().wait()
