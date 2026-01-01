from telegram import Update
from telegram.ext import ContextTypes, CommandHandler
from config import ADMIN_ID, PANEL_URL
from flask_jwt_extended import create_access_token
from web.app import app
from datetime import timedelta
import logging

logger = logging.getLogger(__name__)

async def panel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Simple integer comparison for security
    if user_id != int(ADMIN_ID):
        await update.message.reply_text("⛔️ 您没有权限访问后台。")
        return

    try:
        # Generate Magic Link
        # We need app context to access JWT secret key for signing
        with app.app_context():
            # Create a token that expires in 15 minutes
            # identity should match what we check in web/routes.py (str or int)
            access_token = create_access_token(identity=str(user_id), expires_delta=timedelta(minutes=15))
        
        # Construct URL
        base_url = PANEL_URL.rstrip('/')
        magic_link = f"{base_url}/magic_login?token={access_token}"
        
        # Send link
        await update.message.reply_text(
            f"🔓 *后台管理面板登录链接*\n\n"
            f"点击下方链接即可免密登录（15分钟内有效）：\n\n"
            f"[点击登录后台]({magic_link})\n\n"
            f"⚠️ 请勿将此链接分享给他人。",
            parse_mode='Markdown',
            disable_web_page_preview=True
        )
            
    except Exception as e:
        logger.error(f"Failed to generate panel link: {e}")
        await update.message.reply_text("❌ 生成链接失败，请检查服务器日志。")

panel_handler = CommandHandler("panel", panel_command)
