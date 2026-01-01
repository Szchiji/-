from flask import Blueprint, render_template, request, redirect, session, jsonify, url_for
from app import db, global_bot, global_loop
from app.models import User, Chat, Config, DEFAULT_FIELDS, DEFAULT_CHAT_SETTINGS
from app.services import get_conf, set_conf
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters
import os, jwt, time, json, asyncio, re
from datetime import datetime

core_bp = Blueprint('core', __name__, url_prefix='/core', template_folder='templates')

# --- 网页路由 ---

@core_bp.route('/')
def index():
    if not session.get('logged_in'): return render_template('base.html', page='login')
    # 首页显示所有已发现的群组/频道
    chats = Chat.query.order_by(Chat.id.desc()).all()
    return render_template('dashboard.html', page='dashboard', chats=chats)

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

# 🌟 新增：独立群组设置页
@core_bp.route('/settings/<int:chat_id>')
def page_chat_settings(chat_id):
    if not session.get('logged_in'): return redirect('/core')
    chat = Chat.query.get(chat_id)
    if not chat: return "Chat not found", 404
    
    # 合并默认配置，防止新字段报错
    current_settings = json.loads(chat.settings or '{}')
    settings = DEFAULT_CHAT_SETTINGS.copy()
    settings.update(current_settings)
    
    fields = get_conf('fields', DEFAULT_FIELDS)
    return render_template('chat_settings.html', page='dashboard', chat=chat, s=settings, fields=fields)

@core_bp.route('/magic_login')
def magic_login():
    token = request.args.get('token')
    if token and jwt.decode(token, os.getenv('SECRET_KEY'), algorithms=['HS256']).get('uid') == int(os.getenv('ADMIN_ID', 0)):
        session['logged_in'] = True
        return redirect('/core')
    return "Link Invalid", 403

# --- API ---

@core_bp.route('/api/save_chat_settings', methods=['POST'])
def api_save_chat_settings():
    if not session.get('logged_in'): return "403", 403
    data = request.json
    chat_id = data.get('chat_id')
    settings = data.get('settings')
    
    chat = Chat.query.get(chat_id)
    if chat:
        chat.settings = json.dumps(settings, ensure_ascii=False)
        db.session.commit()
        return jsonify({"status": "ok"})
    return jsonify({"status": "err", "msg": "Chat not found"})

@core_bp.route('/api/save_user', methods=['POST'])
def api_save_user(): # ... (保持不变)
    if not session.get('logged_in'): return "403", 403
    data = request.json
    try:
        tg_id = int(data.get('tg_id'))
        user = User.query.filter_by(tg_id=tg_id).first()
        if not user:
            user = User(tg_id=tg_id)
            db.session.add(user)
        user.profile_data = json.dumps(data.get('profile', {}), ensure_ascii=False)
        db.session.commit()
        return jsonify({"status": "ok"})
    except Exception as e: return jsonify({"status": "err", "msg": str(e)})

@core_bp.route('/api/delete_user', methods=['POST'])
def api_delete_user(): # ... (保持不变)
    User.query.filter_by(id=request.json.get('id')).delete()
    db.session.commit()
    return jsonify({"status": "ok"})

@core_bp.route('/api/save_fields', methods=['POST'])
def api_save_fields(): # ... (保持不变)
    set_conf('fields', request.json)
    return jsonify({"status": "ok"})

# --- 机器人逻辑 ---

async def bot_start(update: Update, context):
    if update.effective_chat.type == 'private' and update.effective_user.id == int(os.getenv('ADMIN_ID', 0)):
        token = jwt.encode({'uid': update.effective_user.id, 'exp': time.time()+3600}, os.getenv('SECRET_KEY'), algorithm='HS256')
        url = f"{os.getenv('RAILWAY_PUBLIC_DOMAIN')}/core/magic_login?token={token}"
        await update.message.reply_html(f"💼 <b>管理后台：</b>\n<a href='{url}'>点击进入</a>")

async def bot_handler(update: Update, context):
    if not update.effective_chat: return
    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type
    
    # 1. 自动发现：记录群组/频道
    if chat_type in ['group', 'supergroup', 'channel']:
        from app import create_app
        with create_app().app_context():
            chat = Chat.query.get(chat_id)
            if not chat:
                chat = Chat(id=chat_id, title=update.effective_chat.title, type=chat_type)
                db.session.add(chat)
                db.session.commit()
            
            # 🌟 获取该群组的独立配置
            settings = json.loads(chat.settings or '{}')
            # 如果是新群，settings可能是空的，使用默认值
            if not settings: settings = DEFAULT_CHAT_SETTINGS

            if not update.message or not update.message.text: return
            text = update.message.text.strip()
            user = update.effective_user

            # 2. 认证用户自动点赞
            if settings.get('auto_like', True):
                if User.query.filter_by(tg_id=user.id).first():
                    try: await update.message.set_reaction(settings.get('like_emoji', '❤️'))
                    except: pass

            # 3. 打卡
            if text == settings.get('checkin_cmd', '打卡'):
                if not settings.get('checkin_open', True): return
                
                u = User.query.filter_by(tg_id=user.id).first()
                delay = int(settings.get('del_time', 30))
                
                if not u:
                    msg = await update.message.reply_html(settings.get('msg_fail', '未认证'))
                else:
                    now = datetime.now()
                    if u.checkin_time and u.checkin_time.date() == now.date():
                        msg = await update.message.reply_html(settings.get('msg_repeat', '已打卡'))
                    else:
                        u.checkin_time = now
                        u.online = True
                        u.last_chat_id = chat_id # 记录在哪个群打的卡
                        db.session.commit()
                        msg = await update.message.reply_html(settings.get('msg_success', '成功'))
                
                try: context.job_queue.run_once(lambda c: c.job.data.delete(), delay, data=update.message)
                except: pass
                context.job_queue.run_once(lambda c: c.job.data.delete(), delay, data=msg)

            # 4. 查询
            if text == settings.get('query_cmd', '查询'):
                # 只查在这个群打卡，或者全局在线的用户？
                # 通常是查全局在线，但显示格式由本群配置决定
                today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                users = User.query.filter(User.checkin_time >= today_start, User.online == True).all()
                
                delay = int(settings.get('del_time', 30))
                if not users:
                    msg = await update.message.reply_text("😢 今日无打卡")
                else:
                    header = settings.get('msg_query_head', '')
                    tpl = settings.get('user_template', '')
                    fields_map = {f['key']: f['label'] for f in get_conf('fields', DEFAULT_FIELDS)}
                    
                    lines = []
                    for u in users:
                        try:
                            d = json.loads(u.profile_data)
                            # 替换变量: {昵称Value} -> d['name']
                            line = tpl.replace("{onlineEmoji}", settings.get('online_emoji','🟢'))
                            for k, label in fields_map.items():
                                line = line.replace(f"{{{label}Value}}", str(d.get(k,'')))
                            lines.append(re.sub(r'\{.*?\}', '', line))
                        except: continue
                    msg = await update.message.reply_html(header + "\n".join(lines))
                
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
