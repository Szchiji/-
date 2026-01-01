from telegram import Update
from telegram.ext import CommandHandler, CallbackContext
from models import User, db
from datetime import datetime
from bot.jobs import delete_message
from web.app import app
import logging

logger = logging.getLogger(__name__)

async def checkin(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    
    try:
        with app.app_context():
            user = User.query.filter_by(telegram_id=user_id).first()
            if not user:
                await update.message.reply_text('请先认证！')
                return
            user.checkin_time = datetime.now()
            user.online = True
            db.session.commit()
        
        await update.message.reply_text('已打卡！在线状态：🟢')
        context.job_queue.run_once(delete_message, 30, data={'chat_id': update.message.chat_id, 'message_id': update.message.message_id})
    except Exception as e:
        logger.error(f"Checkin error for user {user_id}: {e}")
        await update.message.reply_text('打卡失败，请稍后重试。')

checkin_handler = CommandHandler('daka', checkin)
