from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from telegram.ext import CallbackContext
from models import ScheduledMessage, Button
from bot.jobs import send_scheduled_message
from web.app import app

scheduler = AsyncIOScheduler()

def load_scheduled_tasks(application):
    with app.app_context():
        tasks = ScheduledMessage.query.filter_by(enabled=True).all()
        for task in tasks:
            scheduler.add_job(
                send_scheduled_message,
                trigger=CronTrigger.from_crontab(task.schedule_time, timezone=task.timezone),
                args=(application.bot, task.chat_id, task.message_text, task.media_type, task.media_url, task.caption, task.silent, task.retry_count, task.condition)
            )
    scheduler.start()
