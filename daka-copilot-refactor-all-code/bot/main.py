import sys
import os
import logging
import asyncio
from telegram.ext import Application
from dotenv import load_dotenv

# 确保能找到根目录的 config 和 web 模块
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config import TOKEN, MAIN_CHAT_ID
from web.app import app  # 导入 flask app 以获取数据库上下文
from models import db
from bot.handlers.start import start_handler
from bot.handlers.checkin import checkin_handler
from bot.handlers.query import query_online_handler
from bot.handlers.auto_reply import auto_reply_handler
from bot.handlers.force_subscribe import force_subscribe_handler, force_subscribe_message_handler, force_subscribe_update_handler
from bot.handlers.points import points_handler, top_handler, lottery_handler, shop_handler, buy_handler
from bot.handlers.callback import callback_handler
from bot.handlers.admin import panel_handler  # New admin panel handler
from bot.jobs import check_expiration, check_points_expiration
from bot.handlers.scheduled import load_scheduled_tasks
from apscheduler.schedulers.asyncio import AsyncIOScheduler

load_dotenv()
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def main():
    if not TOKEN:
        logger.error("❌ 环境变量 TOKEN 缺失，请检查配置！")
        return

    # 初始化 Telegram Application
    application = Application.builder().token(TOKEN).build()

    # 注册所有处理器
    application.add_handler(start_handler)
    application.add_handler(panel_handler)  # Register panel handler
    application.add_handler(checkin_handler)
    application.add_handler(query_online_handler)
    application.add_handler(auto_reply_handler)
    application.add_handler(force_subscribe_handler)
    application.add_handler(force_subscribe_message_handler)
    application.add_handler(force_subscribe_update_handler)
    application.add_handler(points_handler)
    application.add_handler(top_handler)
    application.add_handler(lottery_handler)
    application.add_handler(shop_handler)
    application.add_handler(buy_handler)
    application.add_handler(callback_handler)

    # 错误处理
    async def error_handler(update, context):
        logger.error(f"⚠️ 机器人运行错误: {context.error}")

    application.add_error_handler(error_handler)

    # 在 Flask 应用上下文中运行
    with app.app_context():
        # 初始化定时任务
        load_scheduled_tasks(application)
        scheduler = AsyncIOScheduler()
        scheduler.add_job(check_expiration, 'cron', hour=0, args=(application, MAIN_CHAT_ID))
        scheduler.add_job(check_points_expiration, 'cron', hour=0, args=(application, MAIN_CHAT_ID))
        scheduler.start()

        logger.info("🚀 机器人正在启动运行 (Polling模式)...")
        # 启动机器人
        await application.initialize()
        await application.start()
        await application.updater.start_polling()
        
        # 保持运行
        while True:
            await asyncio.sleep(1)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("机器人已停止")
