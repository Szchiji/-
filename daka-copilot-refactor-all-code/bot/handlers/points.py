from telegram import Update
from telegram.ext import CommandHandler, CallbackContext
from models import Points, db
from web.app import app
import logging

logger = logging.getLogger(__name__)

async def view_points(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    try:
        with app.app_context():
            point = Points.query.filter_by(user_id=user_id).first()
            points_value = point.points if point else 0
        await update.message.reply_text(f'你的积分: {points_value}')
    except Exception as e:
        logger.error(f"Error viewing points for user {user_id}: {e}")
        await update.message.reply_text('查询积分失败，请稍后重试。')

async def top_points(update: Update, context: CallbackContext):
    try:
        with app.app_context():
            top = Points.query.order_by(Points.points.desc()).limit(10).all()
            text = '积分排行:\n'
            for i, p in enumerate(top, 1):
                text += f'{i}. 用户{p.user_id}: {p.points}\n'
        await update.message.reply_text(text)
    except Exception as e:
        logger.error(f"Error fetching top points: {e}")
        await update.message.reply_text('查询排行榜失败，请稍后重试。')

points_handler = CommandHandler('points', view_points)
top_handler = CommandHandler('top', top_points)
