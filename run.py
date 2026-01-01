import os
import asyncio
import threading
import logging
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from models import db, User
from web.routes import web_bp
from datetime import datetime

# 配置
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

DB_URI = os.getenv('DATABASE_URL', 'sqlite:///bot.db')
if DB_URI.startswith("postgres://"):
    DB_URI = DB_URI.replace("postgres://", "postgresql://", 1)

TOKEN = os.getenv('TOKEN')
PORT = int(os.getenv('PORT', 5000))

# 初始化 Flask
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = DB_URI
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'secret'

db.init_app(app)
app.register_blueprint(web_bp)

# --- 重新实现的 Bot 逻辑 (为了解决上下文问题，直接在这里引用 app context) ---
async def bot_start(update: Update, context):
    u = update.effective_user
    with app.app_context():
        if not User.query.filter_by(telegram_id=u.id).first():
            db.session.add(User(telegram_id=u.id, username=u.username))
            db.session.commit()
    await update.message.reply_text("Bot 已启动！(完整版结构)")

async def bot_daka(update: Update, context):
    uid = update.effective_user.id
    with app.app_context():
        user = User.query.filter_by(telegram_id=uid).first()
        if user:
            user.points += 10
            user.checkin_time = datetime.now()
            db.session.commit()
            await update.message.reply_text(f"打卡成功！当前积分: {user.points}")
        else:
            await update.message.reply_text("请联系管理员注册")

# --- 启动器 ---
def run_flask():
    app.run(host='0.0.0.0', port=PORT, use_reloader=False)

async def run_bot():
    if not TOKEN: return
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", bot_start))
    application.add_handler(CommandHandler("daka", bot_daka))
    
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    
    stop_event = asyncio.Event()
    await stop_event.wait()

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    
    # 启动 Flask
    t = threading.Thread(target=run_flask, daemon=True)
    t.start()
    
    # 启动 Bot
    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        pass
