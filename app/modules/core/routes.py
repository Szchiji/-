from flask import Blueprint, render_template, request, redirect, session, jsonify
from app import db
from app.models import BotGroup, GroupUser, DEFAULT_FIELDS, DEFAULT_SYSTEM
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions, ChatMember
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ChatMemberHandler, filters
import os, jwt, time, json, asyncio, re, requests, math
from datetime import datetime, timedelta

core_bp = Blueprint('core', __name__, url_prefix='/core', template_folder='templates')

# 全局变量
global_ptb_app = None
global_bot_loop = None

# --- Webhook 接收端点 ---
@core_bp.route('/webhook', methods=['POST'])
def webhook():
    if not global_ptb_app or not global_bot_loop:
        return "Bot Not Ready", 503
    try:
        json_data = request.get_json(force=True)
        update = Update.de_json(json_data, global_ptb_app.bot)
        asyncio.run_coroutine_threadsafe(global_ptb_app.process_update(update), global_bot_loop)
        return "OK", 200
    except Exception as e:
        print(f"❌ Webhook Error: {e}")
        return "Error", 200

# --- Context ---
@core_bp.context_processor
def inject_context():
    data = {'all_groups': []}
    if session.get('logged_in'):
        data['all_groups'] = BotGroup.query.order_by(BotGroup.is_active.desc(), BotGroup.updated_at.desc()).all()
    gid = session.get('current_group_id')
    if gid: data['current_group'] = BotGroup.query.get(gid)
    return data

def safe_int(val, default=0):
    if val is None: return default
    if isinstance(val, str) and val.strip() == '': return default
    try: return int(val)
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

# --- Web Routes ---
@core_bp.route('/')
def index(): return redirect('/core/select_group') if session.get('logged_in') else render_template('base.html', page='login')

@core_bp.route('/select_group')
def page_select_group():
    if not session.get('logged_in'): return redirect('/core')
    session.pop('current_group_id', None)
    groups = BotGroup.query.order_by(BotGroup.is_active.desc(), BotGroup.updated_at.desc()).all()
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

# --- APIs ---
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
        tg_id_raw = d.get('tg_id')
        if not tg_id_raw: return jsonify({"status": "err", "msg": "Telegram ID 不能为空"})
        tg_id = int(tg_id_raw)
        
        u = GroupUser.query.filter_by(group_id=gid, tg_id=tg_id).first()
        if not u:
            u = GroupUser(group_id=gid, tg_id=tg_id)
            db.session.add(u)
        u.profile_data = json.dumps(d.get('profile', {}), ensure_ascii=False)
        
        days_raw = d.get('add_days')
        days = int(days_raw) if days_raw and str(days_raw).strip() else 0
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
        if request.json.get('action') == 'delete':
             GroupUser.query.filter_by(group_id=group.id).delete()
             db.session.delete(group)
        else:
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

async def run_bot():
    global global_ptb_app, global_bot_loop
    global_bot_loop = asyncio.get_running_loop()
    
    token = os.getenv('TOKEN')
    app_bot = Application.builder().token(token).build()
    
    app_bot.add_handler(CommandHandler("start", bot_start))
    app_bot.add_handler(CallbackQueryHandler(pagination_callback))
    app_bot.add_handler(ChatMemberHandler(chat_member_handler, ChatMemberHandler.MY_CHAT_MEMBER))
    app_bot.add_handler(MessageHandler(filters.ALL, bot_handler))
    
    await app_bot.initialize()
    await app_bot.start()
    
    global_ptb_app = app_bot
    
    domain = os.getenv('RAILWAY_PUBLIC_DOMAIN')
    if domain:
        url = f"https://{domain}/core/webhook"
        print(f"🔗 设置 Webhook: {url}", flush=True)
        await app_bot.bot.set_webhook(url)
        await asyncio.Event().wait()
    else:
        print("📡 本地模式: 启动 Polling...", flush=True)
        await app_bot.updater.start_polling()
        await asyncio.Event().wait()

# --- 业务逻辑 ---

async def bot_start(update: Update, context):
    user_id = update.effective_user.id
    admin_id = int(os.getenv('ADMIN_ID', 0))
    if user_id == admin_id:
        token = jwt.encode({'uid': user_id, 'exp': time.time()+3600}, os.getenv('SECRET_KEY'), algorithm='HS256')
        domain = os.getenv('RAILWAY_PUBLIC_DOMAIN', '').rstrip('/')
        url = f"https://{domain}/core/magic_login?token={token}" if domain else f"/core/magic_login?token={token}"
        await update.message.reply_html(f"💼 <b>后台入口：</b>\n<a href='{url}'>点击管理</a>")
    else:
        await update.message.reply_html(f"👋 你好！我是打卡机器人。\n你的 ID 是：<code>{user_id}</code>")

def do_like(chat_id, message_id, emoji):
    """
    发送点赞 (使用原生 API，不依赖库版本)
    """
    token = os.getenv('TOKEN')
    try: 
        # 直接调用 Telegram 官方 API
        url = f"https://api.telegram.org/bot{token}/setMessageReaction"
        payload = {
            "chat_id": chat_id, 
            "message_id": message_id, 
            "reaction": [{"type": "emoji", "emoji": emoji}]
        }
        resp = requests.post(url, json=payload, timeout=5)
        # 打印一下结果，方便调试
        if resp.status_code != 200:
            print(f"⚠️ [Like API] 失败: {resp.text}", flush=True)
        else:
            print(f"✅ [Like API] 成功: {emoji}", flush=True)
    except Exception as e:
        print(f"❌ [Like Func] 出错: {e}", flush=True)

async def check_expiration_and_mute(context, group_id, user_id, chat_id, conf):
    from app import create_app
    with create_app().app_context():
        u = GroupUser.query.filter_by(group_id=group_id, tg_id=int(user_id)).first()
        if not u or not u.expiration_date: return
        now = datetime.now()
        if u.expiration_date < now and not u.is_banned:
            try: 
                await context.bot.restrict_chat_member(chat_id=chat_id, user_id=user_id, permissions=ChatPermissions(can_send_messages=False))
                u.is_banned = True
                db.session.commit()
                await context.bot.send_message(chat_id=chat_id, text=conf.get('msg_expired_ban', '⛔️ 过期禁言'), parse_mode='HTML')
            except: pass
        elif u.expiration_date > now and u.is_banned:
            try:
                await context.bot.restrict_chat_member(chat_id=chat_id, user_id=user_id, permissions=ChatPermissions(can_send_messages=True, can_send_media_messages=True, can_send_other_messages=True))
                u.is_banned = False
                db.session.commit()
            except: pass

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
    if page > 1: nav_row.append(InlineKeyboardButton("⬅️", callback_data=f"pg|{page-1}|{safe_kw}"))
    nav_row.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
    if page < total_pages: nav_row.append(InlineKeyboardButton("➡️", callback_data=f"pg|{page+1}|{safe_kw}"))
    if nav_row: buttons.append(nav_row)
    custom_btns = conf.get('custom_buttons', '')
    if custom_btns:
        try:
            btn_list = json.loads(custom_btns)
            row = []
            for btn in btn_list:
                row.append(InlineKeyboardButton(btn['text'], url=btn['url']))
                if len(row) == 2:
                    buttons.append(row)
                    row = []
            if row: buttons.append(row)
        except: pass
    return InlineKeyboardMarkup(buttons)

async def do_query_page(chat_id, group_id, conf, fields, kw=None, page=1):
    from app import create_app
    with create_app().app_context():
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        base = GroupUser.query.filter(GroupUser.group_id == group_id, GroupUser.checkin_time >= today, GroupUser.online == True)
        if kw:
            base = base.filter(GroupUser.profile_data.contains(kw))
            header = conf.get('msg_filter_header', '🔍 <b>筛选结果：</b>')
        else:
            header = conf.get('msg_query_header', '🔍 <b>今日在线：</b>')
        users = base.order_by(GroupUser.checkin_time.desc()).all()
        if not users: return None, None, None
        page_size = safe_int(conf.get('page_size'), 10)
        total_pages = math.ceil(len(users) / page_size) or 1
        if page > total_pages: page = total_pages
        if page < 1: page = 1
        text = build_list_text(users, page, page_size, conf, fields, header)
        markup = get_pagination_markup(page, total_pages, kw, conf)
        return text, markup, users

async def chat_member_handler(update: Update, context):
    chat = update.effective_chat
    if chat.type not in ['group', 'supergroup', 'channel']: return
    my_chat_member = update.my_chat_member
    if not my_chat_member: 
        await get_group_info_safe(chat)
        return
    new_status = my_chat_member.new_chat_member.status
    from app import create_app
    with create_app().app_context():
        bg = BotGroup.query.filter_by(chat_id=str(chat.id)).first()
        if new_status in [ChatMember.LEFT, ChatMember.BANNED]:
            if bg:
                bg.is_active = False 
                db.session.commit()
        elif new_status in [ChatMember.MEMBER, ChatMember.ADMINISTRATOR]:
            if not bg:
                bg = BotGroup(chat_id=str(chat.id), type=chat.type, title=chat.title, is_active=True)
                bg.fields_config = json.dumps(DEFAULT_FIELDS, ensure_ascii=False)
                db.session.add(bg)
            else:
                bg.is_active = True 
                bg.title = chat.title 
            db.session.commit()

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
    gid = g_info['id']
    if not update.effective_user: return
    user = update.effective_user
    text = msg.text.strip() if msg.text else ""

    # ⚡️ 修复点：直接调用 do_like，跳过库的兼容性问题
    if conf.get('auto_like'):
        from app import create_app
        with create_app().app_context():
            exists = db.session.query(GroupUser.id).filter_by(group_id=gid, tg_id=user.id).scalar()
            if exists:
                emoji = conf.get('like_emoji', '❤️')
                print(f"👍 [Like] 给用户 {user.id} 点赞: {emoji}", flush=True)
                
                # 直接调用同步函数
                do_like(msg.chat.id, msg.message_id, emoji)
                
                if conf.get('auto_mute_expired'): 
                    await check_expiration_and_mute(context, gid, user.id, msg.chat.id, conf)

    checkin_cmds = [c.strip() for c in conf.get('checkin_cmd', '打卡').split(',')]
    if text in checkin_cmds:
        if not conf.get('checkin_open'): return
        from app import create_app
        with create_app().app_context():
            u = GroupUser.query.filter_by(group_id=gid, tg_id=int(user.id)).first()
            if not u: r = await msg.reply_html(conf.get('msg_not_registered'))
            elif u.checkin_time and u.checkin_time.date() == datetime.now().date(): r = await msg.reply_html(conf.get('msg_repeat_checkin'))
            else:
                u.checkin_time = datetime.now()
                u.online = True
                db.session.commit()
                r = await msg.reply_html(conf.get('msg_checkin_success'))
            context.job_queue.run_once(lambda c: c.job.data.delete(), safe_int(conf.get('checkin_del_time'), 30), data=r)
        return

    query_cmds = [c.strip() for c in conf.get('query_cmd', '查询').split(',')]
    kw = None
    is_search = False

    if conf.get('query_open') and text in query_cmds:
        is_search = True
        kw = None 
    elif conf.get('query_filter_open'):
        matched_prefix = next((c for c in query_cmds if text.startswith(c + " ")), None)
        if matched_prefix:
            kw = text[len(matched_prefix):].strip()
            is_search = True
        elif len(text) > 0 and len(text) < 15 and not text.startswith('/'):
            kw = text
            is_search = True

    if is_search:
        text_resp, markup, users = await do_query_page(msg.chat.id, gid, conf, fields, kw, 1)
        if kw and not users: return 
        if not kw and not users:
            text_resp = "😢 今日暂无打卡"
            markup = None
        if text_resp:
            sent = await msg.reply_html(text_resp, reply_markup=markup, disable_web_page_preview=True)
            context.job_queue.run_once(lambda c: c.job.data.delete(), safe_int(conf.get('query_del_time'), 60), data=sent)

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
    try: 
        await query.edit_message_text(text=text, parse_mode='HTML', reply_markup=markup, disable_web_page_preview=True)
        await query.answer()
    except: await query.answer()
