import logging
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from config import Config
from models import db, User, AutoReply
from web import app  # 导入 Flask app 以获取数据库上下文

# 配置日志
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(f"你好 {user.first_name}，欢迎使用社群助手！\n发送 /daka 进行打卡。")

async def checkin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_id = update.effective_user.id
    username = update.effective_user.username
    
    # 使用 Flask 的 app context 访问数据库
    with app.app_context():
        user = User.query.filter_by(telegram_id=tg_id).first()
        if not user:
            # 自动注册新用户（或提示去网页注册）
            user = User(telegram_id=tg_id, username=username)
            db.session.add(user)
        
        user.last_checkin = datetime.now()
        user.is_online = True
        user.points += 10 # 打卡加分
        db.session.commit()
        
        current_points = user.points

    await update.message.reply_text(f"✅ 打卡成功！\n当前积分：{current_points}\n状态：在线 🟢")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if not text:
        return

    # 简单的自动回复逻辑
    with app.app_context():
        # 查找包含匹配的规则
        rules = AutoReply.query.filter_by(match_type='contains').all()
        for rule in rules:
            if rule.keyword in text:
                await update.message.reply_text(rule.reply_content)
                return

# --- Main Execution ---

def run_bot():
    application = Application.builder().token(Config.BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("daka", checkin))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot is starting...")
    application.run_polling()

if __name__ == '__main__':
    run_bot()
