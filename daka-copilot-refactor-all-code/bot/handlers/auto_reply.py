import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import MessageHandler, filters, CallbackContext
from models import AutoReply, ReplyLog, Button, db
from datetime import datetime
from web.app import app
import logging

logger = logging.getLogger(__name__)

async def handle_auto_reply(update: Update, context: CallbackContext):
    try:
        if update.message and update.message.text:
            text = update.message.text.lower()
            user_id = update.message.from_user.id
            message_id = update.message.message_id
            
            with app.app_context():
                rules = AutoReply.query.filter_by(status='active').order_by(AutoReply.priority.desc()).all()
                for rule in rules:
                    if rule.match_type == 'exact' and text == rule.keyword.lower() or \
                       rule.match_type == 'contains' and rule.keyword.lower() in text or \
                       rule.match_type == 'regex' and re.search(rule.keyword, text, re.IGNORECASE):
                        try:
                            reply = rule.reply_text.format(username=update.message.from_user.username or '用户')
                        except (KeyError, ValueError) as e:
                            # If template contains unknown placeholders or is malformed, use as-is
                            logger.warning(f"Template formatting error for rule {rule.id}: {e}")
                            reply = rule.reply_text
                        buttons = Button.query.filter_by(reply_id=rule.id).all()
                        keyboard = []
                        row = []
                        for btn in buttons:
                            if btn.url:
                                row.append(InlineKeyboardButton(btn.text, url=btn.url))
                            elif btn.callback_data:
                                row.append(InlineKeyboardButton(btn.text, callback_data=btn.callback_data))
                            if len(row) == 2:
                                keyboard.append(row)
                                row = []
                        if row:
                            keyboard.append(row)
                        markup = InlineKeyboardMarkup(keyboard) if keyboard else None
                        if rule.media_type == 'photo' and rule.media_url:
                            await context.bot.send_photo(chat_id=update.effective_chat.id, photo=rule.media_url, caption=reply, reply_to_message_id=message_id, has_spoiler=rule.has_spoiler, reply_markup=markup)
                        # 其他媒体类似
                        else:
                            await update.message.reply_text(reply, reply_to_message_id=message_id, reply_markup=markup)
                        log = ReplyLog.query.filter_by(rule_id=rule.id, user_id=user_id).first()
                        if log:
                            log.count += 1
                            log.timestamp = datetime.now()
                        else:
                            log = ReplyLog(rule_id=rule.id, user_id=user_id)
                            db.session.add(log)
                        db.session.commit()
                        break
    except Exception as e:
        logger.error(f"Error handling auto reply: {e}")

auto_reply_handler = MessageHandler(filters.TEXT & ~filters.COMMAND, handle_auto_reply)
