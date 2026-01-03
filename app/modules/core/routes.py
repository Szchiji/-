from flask import Blueprint, render_template, request, redirect, session, jsonify
from app import db
from app.models import BotGroup, GroupUser, DEFAULT_FIELDS, DEFAULT_SYSTEM
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions, ChatMember
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ChatMemberHandler, filters
import os, jwt, time, json, asyncio, re, requests, math
from datetime import datetime, timedelta

core_bp = Blueprint('core', __name__, url_prefix='/core', template_folder='templates')

# --- 全局变量 ---
global_ptb_app = None
global_bot_loop = None

# --- Webhook ---
@core_bp.route('/webhook', methods=['POST'])
def webhook():
    if not global_ptb_app or not global_bot_loop: return "Bot Not Ready", 503
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
            # 兼容旧数据结构 {config: {...}}
            if isinstance(c, dict) and 'config' in c: c = c['config']
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
    users = GroupUser.query.filter_by(group_id=gid).order_by(GroupUser.updated_at.desc()).limit(200).all()
    # ⚡️ 预处理 JSON，避免模板报错
    for u in users:
        try: u.profile_dict = json.loads(u.profile_data) if u.profile_data else {}
        except: u.profile_dict = {}
    return render_template('users.html', page='users', group=group, users=users, fields=get_group_fields(group))

@core_bp.route('/group/<int:gid>/fields')
def page_fields(gid):
    if not session.get('logged_in'): return redirect('/core')
    session['current_group_id'] = gid
    group = BotGroup.query.get_or_404(gid)
    return render_template('fields.html', page='fields', group=group, fields_json=json.dumps(get_group_fields(group)))

@core_bp.route('/group/<int:gid>/settings')
def page_settings(gid):
    if not session.get('logged_in'): return redirect('/core')
    session['current_group_id'] = gid
    group = BotGroup.query.get_or_404(gid)
    return render_template('settings.html', page='settings', group=group, conf=get_group_conf(group), fields=get_group_fields(group))

# --- API Routes ---
@core_bp.route('/api/toggle_group', methods=['POST'])
def api_toggle_group():
    if not session.get('logged_in'): return jsonify({'status':'error','msg':'Auth required'})
    d = request.json
    g = BotGroup.query.get(d['id'])
    if not g: return jsonify({'status':'error'})
    if d['action'] == 'delete':
        GroupUser.query.filter_by(group_id=g.id).delete()
        db.session.delete(g)
    db.session.commit()
    return jsonify({'status':'ok'})

@core_bp.route('/api/save_fields', methods=['POST'])
def api_save_fields():
    if not session.get('logged_in'): return jsonify({'status':'error'})
    d = request.json
    group = BotGroup.query.get(session['current_group_id'])
    
    # ⚡️ 兼容 List 和 Dict 两种格式，防止 500 报错
    fields_data = d.get('fields', d) if isinstance(d, dict) else d
    
    group.fields_config = json.dumps(fields_data, ensure_ascii=False)
    db.session.commit()
    return jsonify({'status':'ok'})

@core_bp.route('/api/save_settings', methods=['POST'])
def api_save_settings():
    if not session.get('logged_in'): return jsonify({'status':'error'})
    d = request.json
    group = BotGroup.query.get(d['group_id'])
    group.config = json.dumps(d['config'], ensure_ascii=False)
    db.session.commit()
    return jsonify({'status':'ok'})

@core_bp.route('/api/save_user', methods=['POST'])
def api_save_user():
    if not session.get('logged_in'): return jsonify({'status':'error'})
    d = request.json
    gid = d['group_id']
    uid = d.get('tg_id')
    if not uid: return jsonify({'status':'error','msg':'No ID'})
    
    u = GroupUser.query.filter_by(group_id=gid, tg_id=uid).first()
    if not u:
        u = GroupUser(group_id=gid, tg_id=uid)
        db.session.add(u)
    
    u.profile_data = json.dumps(d['profile'], ensure_ascii=False)
    add = safe_int(d.get('add_days'))
    if add != 0:
        base = u.expiration_date or datetime.now()
        u.expiration_date = base + timedelta(days=add)
        # 解封
        if add > 0 and u.is_banned:
            u.is_banned = False
            try: global_ptb_app.bot.restrict_chat_member(chat_id=BotGroup.query.get(gid).chat_id, user_id=u.tg_id, permissions=ChatPermissions.all_permissions())
            except: pass

    db.session.commit()
    return jsonify({'status':'ok'})

@core_bp.route('/api/delete_user', methods=['POST'])
def api_delete_user():
    if not session.get('logged_in'): return jsonify({'status':'error'})
    GroupUser.query.filter_by(id=request.json['id']).delete()
    db.session.commit()
    return jsonify({'status':'ok'})

@core_bp.route('/api/push_user', methods=['POST'])
def api_push_user():
    if not session.get('logged_in'): return jsonify({'status':'error'})
    try:
        user = GroupUser.query.get(request.json['id'])
        if not user: return jsonify({'status':'error','msg':'User not found'})
        
        group = BotGroup.query.get(user.group_id)
        conf = get_group_conf(group)
        cid = conf.get('push_channel_id')
        
        if not cid: return jsonify({'status':'error','msg':'请先在功能配置中填写推送频道ID'})
        
        # 渲染模板
        tpl = conf.get('push_template', '用户: {tg_id}')
        text = tpl.replace('{tg_id}', str(user.tg_id)).replace('{onlineEmoji}', '🟢' if user.online else '🔴').replace('{序号}', str(user.id))
        
        p = json.loads(user.profile_data or '{}')
        for k,v in p.items(): text = text.replace(f'{{{k}}}', str(v)) 
        
        fields = get_group_fields(group)
        for f in fields:
            val = p.get(f['key'], '')
            text = text.replace(f"{{{f['label']}}}", str(val))

        asyncio.run_coroutine_threadsafe(
            global_ptb_app.bot.send_message(chat_id=cid, text=text, parse_mode='HTML'),
            global_bot_loop
        )
        return jsonify({'status':'ok'})
    except Exception as e:
        return jsonify({'status':'error','msg':str(e)})

@core_bp.route('/magic_login')
def magic_login():
    token = request.args.get('token')
    try:
        data = jwt.decode(token, os.getenv('SECRET_KEY', 'secret'), algorithms=['HS256'])
        session['logged_in'] = True
        return redirect('/core/select_group')
    except:
        return "Invalid Token", 403

@core_bp.route('/logout')
def logout():
    session.clear()
    return "已退出，请关闭窗口。"

# =======================
# 🤖 机器人逻辑 (核心)
# =======================

async def run_bot():
    token = os.getenv('TG_BOT_TOKEN')
    if not token: 
        print("⚠️ 未设置 TG_BOT_TOKEN")
        return

    global global_bot_loop
    global_bot_loop = asyncio.get_running_loop()

    print("🤖 正在初始化 Bot...", flush=True)
    app = Application.builder().token(token).build()
    
    global global_ptb_app
    global_ptb_app = app

    app.add_handler(ChatMemberHandler(on_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    app.add_handler(CallbackQueryHandler(pagination_callback)) # 翻页
    app.add_handler(CommandHandler("start", cmd_start))
    
    await app.initialize()
    await app.start()
    print("✅ Bot 初始化完成 (Webhook 模式)", flush=True)

# 独立点赞函数
def do_like(chat_id, message_id, emoji):
    token = os.getenv('TG_BOT_TOKEN')
    if not token or not emoji: return
    clean_emoji = emoji.strip()
    print(f"👍 [Like] 准备点赞: {clean_emoji}", flush=True)
    try: 
        url = f"https://api.telegram.org/bot{token}/setMessageReaction"
        resp = requests.post(url, json={"chat_id": chat_id, "message_id": message_id, "reaction": [{"type": "emoji", "emoji": clean_emoji}]}, timeout=5)
        if resp.status_code == 200: print("✅ [Like] 成功！", flush=True)
        else: print(f"❌ [Like] 失败: {resp.text}", flush=True)
    except Exception as e: print(f"❌ [Like] 请求异常: {e}", flush=True)

async def cmd_start(update: Update, context):
    """管理员获取后台链接"""
    user_id = update.effective_user.id
    admin_id = safe_int(os.getenv('ADMIN_ID', 0))
    if user_id == admin_id:
        token = jwt.encode({'uid': user_id, 'exp': time.time()+3600}, os.getenv('SECRET_KEY', 'secret'), algorithm='HS256')
        domain = os.getenv('RAILWAY_PUBLIC_DOMAIN', '').rstrip('/')
        url = f"https://{domain}/core/magic_login?token={token}" if domain else f"/core/magic_login?token={token}"
        await update.message.reply_html(f"💼 <b>后台入口：</b>\n<a href='{url}'>点击管理</a>")
    else:
        await update.message.reply_html(f"👋 你好！我是打卡机器人。\n你的 ID 是：<code>{user_id}</code>")

async def on_my_chat_member(update: Update, context):
    try:
        chat = update.effective_chat
        status = update.my_chat_member.new_chat_member.status
        if chat.type in ['group', 'supergroup'] and status in ['administrator', 'member']:
            g = BotGroup.query.filter_by(chat_id=str(chat.id)).first()
            if not g:
                g = BotGroup(chat_id=str(chat.id), title=chat.title, username=chat.username, is_active=True)
                g.fields_config = json.dumps(DEFAULT_FIELDS, ensure_ascii=False) # 初始化默认字段
                db.session.add(g)
                db.session.commit()
                print(f"➕ 新群组注册: {chat.title}")
            
            domain = os.getenv('RAILWAY_PUBLIC_DOMAIN', '')
            if domain:
                token = jwt.encode({'uid': chat.id, 'exp': time.time()+86400*7}, os.getenv('SECRET_KEY', 'secret'), algorithm='HS256')
                url = f"https://{domain}/core/magic_login?token={token}"
                try: await context.bot.send_message(chat.id, f"✅ 机器人已激活！\n\n👉 [点击进入后台管理]({url})", parse_mode='Markdown')
                except: pass
    except Exception as e: print(f"Error in on_my_chat_member: {e}")

async def on_message(update: Update, context):
    try:
        msg = update.effective_message
        chat = update.effective_chat
        user = update.effective_user
        if not msg.text or not chat: return

        # 1. 自动点赞
        group = BotGroup.query.filter_by(chat_id=str(chat.id)).first()
        if group:
            conf = get_group_conf(group)
            if conf.get('auto_like'):
                # 判断是否认证用户
                db_user = GroupUser.query.filter_by(group_id=group.id, tg_id=user.id).first()
                # 如果资料不为空，或者 simply 只要在库里就算认证
                if db_user:
                     emoji = conf.get('like_emoji', '❤️')
                     do_like(chat.id, msg.message_id, emoji)

        if not group: return
        txt = msg.text.strip()
        
        # 2. 打卡
        checkin_cmds = [c.strip() for c in conf.get('checkin_cmd', '打卡').split(',')]
        if conf.get('checkin_open') and txt in checkin_cmds:
            db_user = GroupUser.query.filter_by(group_id=group.id, tg_id=user.id).first()
            if not db_user:
                 await msg.reply_html(conf.get('msg_not_registered', '未认证'))
            else:
                 db_user.checkin_time = datetime.now()
                 db_user.online = True
                 db.session.commit()
                 r = await msg.reply_html(conf.get('msg_checkin_success', '打卡成功'))
                 del_time = safe_int(conf.get('checkin_del_time'), 0)
                 if del_time > 0:
                     context.job_queue.run_once(lambda c: c.job.data.delete(), del_time, data=r)
            return

        # 3. 查询
        query_cmds = [c.strip() for c in conf.get('query_cmd', '查询').split(',')]
        is_search = False
        kw = None
        
        if conf.get('query_open') and txt in query_cmds:
            is_search = True
        elif conf.get('query_filter_open'):
            # 关键词前缀匹配，例如 "查询 深圳"
            for cmd in query_cmds:
                if txt.startswith(cmd + " "):
                    kw = txt[len(cmd):].strip()
                    is_search = True
                    break
            # 或者直接匹配 (如果不带斜杠且长度合适)
            if not is_search and 0 < len(txt) < 15 and not txt.startswith('/'):
                kw = txt
                is_search = True
        
        if is_search:
            fields = get_group_fields(group)
            text_resp, markup, users = await do_query_page(chat.id, group.id, conf, fields, kw, 1)
            # 如果有结果，或者是在明确查全部
            if users or (not kw and not users):
                if not text_resp: text_resp = "😢 暂无数据"
                sent = await msg.reply_html(text_resp, reply_markup=markup, disable_web_page_preview=True)
                del_time = safe_int(conf.get('query_del_time'), 60)
                if del_time > 0:
                    context.job_queue.run_once(lambda c: c.job.data.delete(), del_time, data=sent)

    except Exception as e:
        print(f"Msg Error: {e}")

# --- 分页逻辑 ---
async def do_query_page(chat_id, group_id, conf, fields, kw=None, page=1):
    from app import create_app
    with create_app().app_context():
        # 这里定义查询逻辑
        # 默认查今日已打卡的
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        base = GroupUser.query.filter(GroupUser.group_id == group_id, GroupUser.online == True)
        
        # 如果是搜关键词，就不限“今日”，而是搜全部库
        if kw:
            base = GroupUser.query.filter(GroupUser.group_id == group_id) # 重置base
            base = base.filter(GroupUser.profile_data.contains(kw))
            header = conf.get('msg_filter_header', '🔍 <b>筛选结果：</b>')
        else:
            base = base.filter(GroupUser.checkin_time >= today)
            header = conf.get('msg_query_header', '🔍 <b>今日在线：</b>')
            
        users = base.order_by(GroupUser.checkin_time.desc()).all()
        if not users: return None, None, None
        
        page_size = safe_int(conf.get('page_size'), 10)
        total_pages = math.ceil(len(users) / page_size) or 1
        if page > total_pages: page = total_pages
        if page < 1: page = 1
        
        # 构建文本
        start = (page - 1) * page_size
        current_users = users[start:start+page_size]
        
        tpl = conf.get('template', '{tg_id}')
        f_map = {f['key']: f['label'] for f in fields}
        lines = []
        for idx, u in enumerate(current_users):
            try:
                d = json.loads(u.profile_data or '{}')
                l = tpl.replace("{onlineEmoji}", conf.get('online_emoji',''))
                for k, lbl in f_map.items(): l = l.replace(f"{{{lbl}}}", str(d.get(k,'')))
                l = l.replace("{序号}", str(start + idx + 1))
                l = l.replace("{tg_id}", str(u.tg_id))
                lines.append(re.sub(r'\{.*?\}', '', l)) # 清理未匹配的标签
            except: continue
            
        text = header + "\n\n" + "\n".join(lines)
        
        # 构建按钮
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
            
        return text, InlineKeyboardMarkup(buttons), users

async def pagination_callback(update: Update, context):
    query = update.callback_query
    if query.data == "noop": return await query.answer()
    
    try:
        parts = query.data.split('|')
        page = int(parts[1])
        kw = parts[2] if parts[2] != "None" else None
        
        # 获取群组信息 (复用之前的 safe logic)
        chat = update.effective_chat
        from app import create_app
        with create_app().app_context():
            g = BotGroup.query.filter_by(chat_id=str(chat.id)).first()
            if not g: return await query.answer("Expired")
            
            conf = get_group_conf(g)
            fields = get_group_fields(g)
            
            text, markup, _ = await do_query_page(chat.id, g.id, conf, fields, kw, page)
            if text:
                await query.edit_message_text(text=text, parse_mode='HTML', reply_markup=markup, disable_web_page_preview=True)
    except Exception as e: 
        print(f"Page Error: {e}")
    
    await query.answer()
