from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import ChatPermissions
from telegram.ext import CallbackContext
from models import User, Points, db
from web.app import app
import logging

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

async def check_expiration(context: CallbackContext, chat_id):
    try:
        with app.app_context():
            users = User.query.filter(User.expiration_date < datetime.now()).all()
            for user in users:
                await context.bot.restrict_chat_member(
                    chat_id=chat_id, 
                    user_id=user.telegram_id, 
                    permissions=ChatPermissions(can_send_messages=False)
                )
                logger.info(f"User {user.telegram_id} expired, muted.")
    except Exception as e:
        logger.error(f"Error checking expiration: {e}")

async def check_points_expiration(context: CallbackContext, chat_id):
    try:
        with app.app_context():
            expired_points = Points.query.filter(Points.last_earned < datetime.now() - timedelta(days=30)).all()
            for point in expired_points:
                point.points -= 50
                if point.points < 0:
                    await context.bot.restrict_chat_member(
                        chat_id=chat_id, 
                        user_id=point.user_id, 
                        permissions=ChatPermissions(can_send_messages=False)
                    )
                db.session.commit()
    except Exception as e:
        logger.error(f"Error checking points expiration: {e}")

async def send_scheduled_message(bot, chat_id, message_text, media_type=None, media_url=None, caption=None, silent=False, retry_count=3, condition=None):
    # TODO: Implement condition checking for scheduled messages
    # Condition checking would allow messages to be sent based on dynamic criteria
    # (e.g., online member count, time of day, etc.)
    # Current implementation: Conditions are logged but not evaluated
    if condition:
        logger.warning(f"Condition checking not fully implemented: {condition}")
    
    attempts = 0
    while attempts < retry_count:
        try:
            if media_type == 'photo' and media_url:
                await bot.send_photo(chat_id=chat_id, photo=media_url, caption=caption or message_text, disable_notification=silent)
            # 其他媒体类似
            else:
                await bot.send_message(chat_id=chat_id, text=message_text, disable_notification=silent)
            break
        except Exception as e:
            logger.error(f"Send failed (attempt {attempts + 1}/{retry_count}): {e}")
            attempts += 1

async def delete_message(context: CallbackContext):
    try:
        chat_id = context.job.data['chat_id']
        message_id = context.job.data['message_id']
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception as e:
        logger.error(f"Error deleting message: {e}")
