from telegram import Update
from telegram.ext import CommandHandler, CallbackContext
from models import Item, Points, db
from web.app import app
import logging

logger = logging.getLogger(__name__)

async def shop(update: Update, context: CallbackContext):
    try:
        with app.app_context():
            items = Item.query.all()
            text = '积分商城:\n'
            for item in items:
                text += f'{item.id}. {item.name} - {item.cost}积分 ({item.stock}库存): {item.description}\n'
        
        if not text or text == '积分商城:\n':
            text = '积分商城:\n暂无商品'
        
        await update.message.reply_text(text)
    except Exception as e:
        logger.error(f"Error displaying shop: {e}")
        await update.message.reply_text('查询商城失败，请稍后重试。')

async def buy(update: Update, context: CallbackContext):
    if not context.args:
        await update.message.reply_text('用法: /buy <商品ID>')
        return
    
    try:
        item_id = int(context.args[0])
        user_id = update.message.from_user.id
        
        with app.app_context():
            item = Item.query.get(item_id)
            if not item or item.stock <= 0:
                await update.message.reply_text('商品无效或无库存！')
                return
            
            point = Points.query.filter_by(user_id=user_id).first()
            if not point or point.points < item.cost:
                await update.message.reply_text('积分不足！')
                return
            
            point.points -= item.cost
            item.stock -= 1
            item_name = item.name
            db.session.commit()
        
        await update.message.reply_text(f'兑换成功！获得 {item_name}。')
    except ValueError:
        await update.message.reply_text('商品ID必须是数字！')
    except Exception as e:
        logger.error(f"Error buying item: {e}")
        await update.message.reply_text('兑换失败，请稍后重试。')

shop_handler = CommandHandler('shop', shop)
buy_handler = CommandHandler('buy', buy)
