from telegram import Update
from telegram.ext import CommandHandler, CallbackContext
from datetime import timedelta
from config import ADMIN_ID, PANEL_URL
from flask_jwt_extended import create_access_token
from web.app import app

async def start(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if user_id == ADMIN_ID:
        # Generate magic link using flask-jwt-extended
        # Note: Magic link tokens in URL are a security trade-off for convenience
        # - Pros: Easy to use, no password needed, works across devices
        # - Cons: Token visible in browser history and server logs
        # - Mitigation: Short expiration time (15 minutes), single-use recommended
        with app.app_context():
            access_token = create_access_token(identity=str(user_id), expires_delta=timedelta(minutes=15))
        
        magic_link = f'{PANEL_URL.rstrip("/")}/magic_login?token={access_token}'
        await update.message.reply_text(
            f'🔓 *后台管理面板登录链接*\n\n'
            f'点击下方链接即可免密登录（15分钟内有效）：\n\n'
            f'[点击登录后台]({magic_link})\n\n'
            f'⚠️ 请勿将此链接分享给他人。',
            parse_mode='Markdown',
            disable_web_page_preview=True
        )
    else:
        await update.message.reply_text('欢迎使用机器人！您无权限访问后台。')

start_handler = CommandHandler('start', start)