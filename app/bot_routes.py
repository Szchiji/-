from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from .models import db, User, DEFAULT_FIELDS, DEFAULT_SYSTEM
from .utils import get_conf
from . import global_bot, global_loop
import os
import jwt
import time
import asyncio
import json
import re
from datetime import datetime, timedelta

async def start(update: Update, context):
    if update.effective_user.id == int(os.getenv('ADMIN_ID')):
        token = jwt.encode({'uid': update.effective_user.id, 'exp': time.time()+3600}, os.getenv('SECRET_KEY'), algorithm='HS256')
        url = f"{os.getenv('RAILWAY_PUBLIC_DOMAIN')}/magic_login?token={token}"
        await update.message.reply_text("💼 <b>后台管理</b>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🚀 点击登录", url=url)]]), parse_mode='HTML')

async def dynamic_handler(update: Update, context):
    if not update.message or not update.message.text: return
    text = update.message.text.strip().split()[0]
    sys = get_conf('system', DEFAULT_SYSTEM)
    user = update.effective_user

    if text == sys.get('checkin_cmd'):
        if not sys.get('checkin_open'): return
        with db.session.no_autoflush: # 简化上下文
            u = User.query.filter_by(tg_id=user.id).first()
            if not u: return await update.message.reply_text("⚠️ 未认证")
            u.checkin_time = datetime.now()
            u.online = True
            db.session.commit()
            if sys.get('auto_like'):
                try: await update.message.set_reaction(sys.get('like_emoji', '💯'))
                except: pass
            await update.message.reply_text("✅ 打卡成功")

    if text == sys.get('query_cmd'):
        if not sys.get('query_open'): return
        since = datetime.now() - timedelta(days=1)
        users = User.query.filter(User.checkin_time >= since).all()
        if not users: return await update.message.reply_text("暂无在线")
        
        tpl = sys.get('template', '')
        fields_map = {f['label']: f['key'] for f in get_conf('fields', DEFAULT_FIELDS)}
        msg = ""
        for u in users:
            try:
                d = json.loads(u.profile_data)
                line = tpl.replace("{onlineEmoji}", sys['online_emoji'] if u.online else sys['offline_emoji'])
                for label, key in fields_map.items():
                    line = line.replace(f"{{{label}}}", str(d.get(key, '')))
                msg += re.sub(r'\{.*?\}', '', line) + "\n\n"
            except: pass
        await update.message.reply_text(msg, parse_mode='HTML', disable_web_page_preview=True)

async def run_bot():
    import app 
    token = os.getenv('TOKEN')
    if not token: return
    app_bot = Application.builder().token(token).build()
    
    # 赋值给全局变量供 Flask 使用
    app.global_bot = app_bot.bot
    app.global_loop = asyncio.get_running_loop()
    
    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(MessageHandler(filters.TEXT, dynamic_handler))
    
    await app_bot.initialize()
    await app_bot.start()
    await app_bot.updater.start_polling()
    await asyncio.Event().wait()
