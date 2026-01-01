from telegram import Update
from telegram.ext import CommandHandler, CallbackContext
from models import Points, db
from web.app import app
import random
import logging

logger = logging.getLogger(__name__)

async def lottery(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    
    try:
        with app.app_context():
            point = Points.query.filter_by(user_id=user_id).first()
            if not point or point.points < 10:
                await update.message.reply_text('积分不足，无法参与抽奖！')
                return
            
            point.points -= 10
            db.session.commit()
            
            if random.random() < 0.1:
                prize = 100
                point.points += prize
                db.session.commit()
                await update.message.reply_text(f'恭喜中奖！获得 {prize} 积分。')
            else:
                await update.message.reply_text('未中奖，继续努力！')
    except Exception as e:
        logger.error(f"Error in lottery for user {user_id}: {e}")
        await update.message.reply_text('抽奖失败，请稍后重试。')

lottery_handler = CommandHandler('lottery', lottery)
