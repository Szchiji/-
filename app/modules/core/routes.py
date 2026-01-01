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
        tg_id = int(d.get('tg_id'))
        u = GroupUser.query.filter_by(group_id=gid, tg_id=tg_id).first()
        if not u:
            u = GroupUser(group_id=gid, tg_id=tg_id)
            db.session.add(u)
        
        # 保存资料
        u.profile_data = json.dumps(d.get('profile', {}), ensure_ascii=False)
        
        # 🆕 处理有效期
        days = int(d.get('add_days', 0))
        if days:
            now = datetime.now()
            # 如果当前已经过期，就从现在开始算；如果没过期，就从原过期时间续费
            base = u.expiration_date if (u.expiration_date and u.expiration_date > now) else now
            u.expiration_date = base + timedelta(days=days)
            # 续费后自动解禁标记
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
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        resp = requests.post(url, json={"chat_id": final_cid, "text": line, "parse_mode": "HTML"})
        
        if resp.status_code == 200: return jsonify({"status": "ok", "msg": "✅ 推送成功"})
        else: return jsonify({"status": "err", "msg": f"推送失败: {resp.text}"})

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
# 🤖 机器人逻辑
# =======================

# --- 辅助：有效期检查 & 禁言 ---
async def check_user_expiration(user_db, chat_id, context, conf):
    """
    检查用户是否过期，并执行禁言/解禁操作
    """
    if not user_db.expiration_date:
        return # 没设置有效期的永久用户

    now = datetime.now()
    try:
        # 情况1：已过期，但还没标记禁言 -> 执行禁言
        if user_db.expiration_date < now and not user_db.is_banned:
            print(f"⛔️ 用户 {user_db.tg_id} 已过期，执行禁言")
            await context.bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_db.tg_id,
                permissions=ChatPermissions(can_send_messages=False) # 禁言
            )
            user_db.is_banned = True
            db.session.commit()
            
            # 发送过期提示
            msg_text = conf.get('msg_expired_ban', '⛔️ 您的认证已过期，已被禁言。')
            await context.bot.send_message(chat_id=chat_id, text=msg_text, parse_mode='HTML')
            return True # 已处理禁言

        # 情况2：未过期（续费了），但状态还是禁言 -> 执行解禁
        elif user_db.expiration_date > now and user_db.is_banned:
            print(f"✅ 用户 {user_db.tg_id} 已续费，执行解禁")
            await context.bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_db.tg_id,
                permissions=ChatPermissions(
                    can_send_messages=True,
                    can_send_media_messages=True,
                    can_send_other_messages=True
                )
            )
            user_db.is_banned = False
            db.session.commit()
            return False

    except Exception as e:
        print(f"⚠️ 权限操作失败: {e}")
    
    return False

# --- 辅助：分页键盘 ---
def get_pagination_markup(page, total_pages, kw, conf):
    buttons = []
    nav_row = []
    safe_kw = kw if kw else "None"
    
    if page > 1:
        nav_row.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"pg|{page-1}|{safe_kw}"))
    if page < total_pages:
        nav_row.append(InlineKeyboardButton("下一页 ➡️", callback_data=f"pg|{page+1}|{safe_kw}"))
    
    nav_row.insert(1 if len(nav_row)==2 else 0, InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
    if nav_row: buttons.append(nav_row)
    
    custom_text = conf.get('custom_btn_text')
    custom_url = conf.get('custom_btn_url')
    if custom_text and custom_url:
        buttons.append([InlineKeyboardButton(custom_text, url=custom_url)])
        
    return InlineKeyboardMarkup(buttons)

# --- 辅助：构建列表文本 ---
def build_list_text(users, page, per_page, conf, fields, header):
    start = (page - 1) * per_page
    end = start + per_page
    current_users = users[start:end]
    
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

# --- 核心查询处理器 ---
async def query_handler(update, context, gid, kw, conf, fields):
    chat_id = update.effective_chat.id
    from app import create_app
    with create_app().app_context():
        # 1. 互斥删除
        current_group = BotGroup.query.get(gid)
        if current_group.last_query_msg_id:
            try: await context.bot.delete_message(chat_id=chat_id, message_id=current_group.last_query_msg_id)
            except: pass 

        # 2. 查询数据
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        base = GroupUser.query.filter(GroupUser.group_id == gid, GroupUser.checkin_time >= today, GroupUser.online == True)
        
        header = conf.get('msg_query_header', '🔍 <b>今日在线：</b>')
        if kw:
            base = base.filter(GroupUser.profile_data.contains(kw))
            header = conf.get('msg_filter_header', '🔍 <b>筛选结果：</b>')
            
        users = base.order_by(GroupUser.checkin_time.desc()).all()
        
        # 3. 发送逻辑
        if not users:
            # 🆕 关键逻辑：如果是智能搜索(kw存在)且没结果，直接静默退出，不发消息也不删用户消息
            if kw and not any(kw.startswith(c) for c in conf.get('query_cmd', '查询').split(',')):
                return
            
            # 如果是明确指令但没数据，才回复
            txt = f"😢 暂无匹配 '{kw}' 的用户" if kw else "😢 本群今日暂无打卡"
            sent = await update.message.reply_text(txt)
            
            # 记录ID
            current_group.last_query_msg_id = sent.message_id
            db.session.commit()
            
            try: context.job_queue.run_once(lambda c: c.job.data.delete(), 5, data=sent)
            except: pass
        else:
            page_size = safe_int(conf.get('page_size'), 10)
            total_pages = ((len(users) - 1) // page_size) + 1
            text = build_list_text(users, 1, page_size, conf, fields, header)
            markup = get_pagination_markup(1, total_pages, kw, conf)
            
            sent_msg = await update.message.reply_html(text, reply_markup=markup)
            
            current_group.last_query_msg_id = sent_msg.message_id
            db.session.commit()
            
            del_time = safe_int(conf.get('query_del_time'), 60)
            try: context.job_queue.run_once(lambda c: c.job.data.delete(), del_time, data=sent_msg)
            except: pass

        # 🆕 只有明确指令查询时，我们才不删除用户指令？
        # 用户需求：打卡和查询指令不删除。
        # 所以这里我们删掉之前的 delete 代码。
        pass

# --- 翻页回调 ---
async def pagination_callback(update: Update, context):
    query = update.callback_query
    if query.data == "noop": return await query.answer()
    
    parts = query.data.split('|') 
    page = int(parts[1])
    kw = parts[2] if parts[2] != "None" else None
    
    chat_id = update.effective_chat.id
    from app import create_app
    with create_app().app_context():
        bg = BotGroup.query.filter_by(chat_id=str(chat_id)).first()
        if not bg: return await query.answer("群组信息失效")
        
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        base = GroupUser.query.filter(GroupUser.group_id == bg.id, GroupUser.checkin_time >= today, GroupUser.online == True)
        if kw: base = base.filter(GroupUser.profile_data.contains(kw))
        users = base.order_by(GroupUser.checkin_time.desc()).all()
        
        if not users: return await query.answer("数据已过期")

        conf = get_group_conf(bg)
        fields = get_group_fields(bg)
        header = conf.get('msg_filter_header') if kw else conf.get('msg_query_header')
        
        page_size = safe_int(conf.get('page_size'), 10)
        total_pages = ((len(users) - 1) // page_size) + 1
        
        if page > total_pages: page = total_pages
        if page < 1: page = 1
        
        text = build_list_text(users, page, page_size, conf, fields, header or '')
        markup = get_pagination_markup(page, total_pages, kw, conf)
        
        try: 
            await query.edit_message_text(text=text, parse_mode='HTML', reply_markup=markup)
            await query.answer()
        except: await query.answer()

async def bot_start(update: Update, context):
    if update.effective_chat.type == 'private' and update.effective_user.id == int(os.getenv('ADMIN_ID', 0)):
        token = jwt.encode({'uid': update.effective_user.id, 'exp': time.time()+3600}, os.getenv('SECRET_KEY'), algorithm='HS256')
        url = f"{os.getenv('RAILWAY_PUBLIC_DOMAIN', '').rstrip('/')}/core/magic_login?token={token}"
        await update.message.reply_html(f"💼 <b>后台入口：</b>\n<a href='{url}'>点击管理</a>")

async def chat_member_handler(update: Update, context):
    if update.effective_chat.type in ['group', 'supergroup', 'channel']:
        from app import create_app
        with create_app().app_context():
            chat = update.effective_chat
            bg = BotGroup.query.filter_by(chat_id=str(chat.id)).first()
            if not bg:
                bg = BotGroup(chat_id=str(chat.id), is_active=True, type=chat.type, title=chat.title)
                db.session.add(bg)
                db.session.commit()

async def bot_handler(update: Update, context):
    msg = update.message or update.channel_post
    if not msg: return
    
    if msg.chat.type not in ['group', 'supergroup', 'channel']: return
    
    from app import create_app
    with create_app().app_context():
        g = BotGroup.query.filter_by(chat_id=str(msg.chat.id)).first()
        if not g:
            g = BotGroup(chat_id=str(msg.chat.id), title=msg.chat.title, is_active=True)
            db.session.add(g)
            db.session.commit()
        
        if not g.is_active: return
        
        conf = get_group_conf(g)
        fields = get_group_fields(g)
        gid = g.id
        
        if not update.effective_user: return
        user = update.effective_user
        text = msg.text.strip() if msg.text else ""

        # 0. 获取数据库用户对象 (用于点赞、有效期检查)
        user_db = GroupUser.query.filter_by(group_id=gid, tg_id=user.id).first()

        # 1. 强制点赞 (HTTP方式)
        if conf.get('auto_like') and user_db:
            token = os.getenv('TOKEN')
            emoji = conf.get('like_emoji', '❤️')
            url = f"https://api.telegram.org/bot{token}/setMessageReaction"
            try:
                requests.post(url, json={
                    "chat_id": msg.chat.id,
                    "message_id": msg.message_id,
                    "reaction": [{"type": "emoji", "emoji": emoji}]
                }, timeout=1)
            except: pass

        # 2. 有效期检查 & 禁言
        if user_db:
            await check_user_expiration(user_db, msg.chat.id, context, conf)

        # 3. 打卡处理 (精确匹配)
        cmds = [c.strip() for c in conf.get('checkin_cmd', '打卡').split(',')]
        if text in cmds:
            if not conf.get('checkin_open'): return
            
            # 🆕 需求：打卡指令不删除。
            # 所以这里不写 delete_message 逻辑。

            delay = safe_int(conf.get('checkin_del_time'), 30)
            
            if not user_db:
                r = await msg.reply_html(conf.get('msg_not_registered'))
            elif user_db.checkin_time and user_db.checkin_time.date() == datetime.now().date():
                r = await msg.reply_html(conf.get('msg_repeat_checkin'))
            else:
                user_db.checkin_time = datetime.now()
                user_db.online = True
                db.session.commit()
                r = await msg.reply_html(conf.get('msg_checkin_success'))
            
            context.job_queue.run_once(lambda c: c.job.data.delete(), delay, data=r)
            return

        # 4. 查询入口
        if conf.get('query_filter_open'):
            q_cmds = [c.strip() for c in conf.get('query_cmd', '查询').split(',')]
            
            # 情况A：精确查询指令
            if text in q_cmds:
                await query_handler(update, context, gid, None, conf, fields)
                return

            # 情况B：指令开头筛选 (如 "查询 福田")
            matched_prefix = next((c for c in q_cmds if text.startswith(c + " ")), None)
            if matched_prefix:
                kw = text[len(matched_prefix):].strip()
                await query_handler(update, context, gid, kw, conf, fields)
                return

            # 情况C：智能匹配 (仅在非指令时触发)
            # 只有当：不以 "/" 开头，且长度 < 10，才尝试去库里搜
            if len(text) < 10 and not text.startswith('/'):
                 # ⚠️ 关键逻辑：这里调用 query_handler，如果库里搜不到，它会静默
                 # 这样就不会导致普通聊天被当成查询
                 await query_handler(update, context, gid, text, conf, fields)

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
