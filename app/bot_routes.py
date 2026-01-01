from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from .models import db, Member
from .utils import get_conf
from .models import DEFAULT_FIELDS
import jwt
import os
import time
import json
import re

async def admin_start(update: Update, context):
    user = update.effective_user
    admin_id = int(os.getenv('ADMIN_ID', 0))
    
    if user.id == admin_id:
        token = jwt.encode({'uid': user.id, 'exp': time.time()+3600}, os.getenv('SECRET_KEY'), algorithm='HS256')
        url = f"{os.getenv('RAILWAY_PUBLIC_DOMAIN')}/magic_login?token={token}"
        await update.message.reply_text(
            "💼 <b>阿福Bot 管理系统</b>",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🚀 进入后台", url=url)]]),
            parse_mode=ParseMode.HTML
        )
    else:
        await update.message.reply_text("👋 欢迎！发送 /online 查询在线用户。")

async def online(update: Update, context):
    sys = get_conf('system_settings', {})
    if sys.get('query_open') is False:
        return await update.message.reply_text("⛔️ 查询功能已关闭")
    
    # 获取在线用户 (简单逻辑: 24h 内有打卡)
    # 实际应根据 last_checkin 判断
    users = Member.query.limit(20).all() # 简化演示
    if not users: return await update.message.reply_text("暂无在线用户")
    
    tpl = get_conf('msg_template', "<b>{onlineEmoji} {老师名字}</b>")
    fields = get_conf('fields', DEFAULT_FIELDS)
    label_map = {f['label']: f['key'] for f in fields}
    
    msg = ""
    for u in users:
        try:
            profile = json.loads(u.profile_data)
            line = tpl
            line = line.replace("{onlineEmoji}", sys.get('online_emoji', '🟢'))
            
            # 动态替换
            for label, key in label_map.items():
                val = profile.get(key, '未填')
                line = line.replace(f"{{{label}}}", str(val))
            
            msg += line + "\n━━━━━━━━━━\n"
        except: continue
        
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

async def run_bot():
    token = os.getenv('TOKEN')
    if not token: return
    
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", admin_start))
    app.add_handler(CommandHandler("online", online))
    # 更多指令可在此添加
    
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
