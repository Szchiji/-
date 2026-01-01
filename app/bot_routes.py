from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from .models import db, User
from .utils import get_conf
from .models import DEFAULT_FIELDS, DEFAULT_SYSTEM
import os
import time
import jwt
import json
import re
from datetime import datetime, timedelta

async def admin_start(update: Update, context):
    user = update.effective_user
    if user.id == int(os.getenv('ADMIN_ID', 0)):
        token = jwt.encode({'uid': user.id, 'exp': time.time()+3600}, os.getenv('SECRET_KEY'), algorithm='HS256')
        url = f"{os.getenv('RAILWAY_PUBLIC_DOMAIN')}/magic_login?token={token}"
        await update.message.reply_text("Login:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Open Admin", url=url)]]))

async def dynamic_handler(update: Update, context):
    if not update.message or not update.message.text: return
    text = update.message.text.strip().split()[0]
    sys = get_conf('system', DEFAULT_SYSTEM)
    user = update.effective_user
    
    # 打卡
    if text == sys.get('checkin_cmd'):
        if not sys.get('checkin_open'): return
        with db.session.no_autoflush: # 避免上下文冲突
            from app import create_app
            app = create_app()
            with app.app_context():
                u = User.query.filter_by(tg_id=user.id).first()
                if not u: return await update.message.reply_text("未认证")
                u.checkin_time = datetime.now()
                u.online = True
                db.session.commit()
                if sys.get('auto_like'):
                    try: await update.message.set_reaction(sys.get('like_emoji', '💯'))
                    except: pass
                await update.message.reply_text("✅ 打卡成功")

    # 查询
    if text == sys.get('query_cmd'):
        if not sys.get('query_open'): return
        from app import create_app
        app = create_app()
        with app.app_context():
            since = datetime.now() - timedelta(days=1)
            users = User.query.filter(User.checkin_time >= since).all()
            if not users: return await update.message.reply_text("暂无在线")
            
            tpl = sys.get('template', '')
            fields = get_conf('fields', DEFAULT_FIELDS)
            label_map = {f['key']: f['label'] for f in fields}
            
            msg = ""
            for u in users:
                try:
                    d = json.loads(u.profile_data)
                    line = tpl.replace("{onlineEmoji}", sys['online_emoji'] if u.online else sys['offline_emoji'])
                    for k, v in d.items():
                        if k in label_map: line = line.replace(f"{{{label_map[k]}}}", str(v))
                    msg += re.sub(r'\{.*?\}', '', line) + "\n\n"
                except: continue
            await update.message.reply_text(msg, parse_mode='HTML', disable_web_page_preview=True)

async def run_bot():
    token = os.getenv('TOKEN')
    if not token: return
    
    app = Application.builder().token(token).build()
    
    # 注入全局变量供 Flask 调用
    from app import global_bot, global_loop
    import app as app_module
    app_module.global_bot = app.bot
    app_module.global_loop = asyncio.get_running_loop()
    
    app.add_handler(CommandHandler("start", admin_start))
    app.add_handler(MessageHandler(filters.TEXT, dynamic_handler))
    
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    await asyncio.Event().wait()
