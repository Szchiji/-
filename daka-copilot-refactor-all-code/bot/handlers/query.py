from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CommandHandler, CallbackContext
from models import User, Config
from flask_caching import Cache
from web.app import app
import logging

logger = logging.getLogger(__name__)

cache = Cache(config={'CACHE_TYPE': 'simple'})

@cache.cached(timeout=60, key_prefix='online_users')
def get_online_users(page, per_page=10):
    with app.app_context():
        return User.query.filter_by(online=True).offset((page-1)*per_page).limit(per_page).all()

async def query_online(update: Update, context: CallbackContext):
    try:
        page = int(context.args[0]) if context.args else 1
        per_page = 10
        users = get_online_users(page, per_page)
        
        with app.app_context():
            template = Config.query.filter_by(key='query_template').first()
            template_value = template.value if template else '{onlineEmoji} {training_title} {price}'
        
        text = ''
        for user in users:
            data = {'onlineEmoji': '🟢' if user.online else '🔴', 'training_title': user.training_title, 'price': user.price}
            text += template_value.format(**data) + '\n'
        
        if not text:
            text = '暂无在线用户'
        
        keyboard = [[InlineKeyboardButton("下一页", callback_data=f'page_{page+1}')]] if len(users) == per_page else []
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        logger.error(f"Error querying online users: {e}")
        await update.message.reply_text('查询在线用户失败，请稍后重试。')

query_online_handler = CommandHandler('online', query_online)
