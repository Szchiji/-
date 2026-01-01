from telegram import Update, ChatMember, ChatPermissions
from telegram.ext import ChatMemberHandler, MessageHandler, filters, CallbackContext
from models import ForceSubscribe, Config, db
from web.app import app
import time
import logging

logger = logging.getLogger(__name__)

# Define default permissions for unmuting users
DEFAULT_PERMISSIONS = ChatPermissions(
    can_send_messages=True,
    can_send_media_messages=True,
    can_send_polls=True,
    can_send_other_messages=True,
    can_add_web_page_previews=True
)

user_check_cache = {}
banned_users = set()

async def handle_new_member(update: Update, context: CallbackContext):
    try:
        new_members = update.message.new_chat_members
        
        with app.app_context():
            rules = ForceSubscribe.query.filter_by(enabled=True).all()
            if not rules:
                return
            
            for user in new_members:
                for rule in rules:
                    member = await context.bot.get_chat_member(chat_id=rule.target_id, user_id=user.id)
                    if member.status in (ChatMember.LEFT, ChatMember.KICKED):
                        await update.message.reply_text(rule.reminder_text)
                        if rule.action == 'mute':
                            await context.bot.restrict_chat_member(
                                chat_id=update.effective_chat.id, 
                                user_id=user.id, 
                                permissions=ChatPermissions(can_send_messages=False)
                            )
                            banned_users.add(user.id)
                        elif rule.action == 'kick':
                            await context.bot.ban_chat_member(chat_id=update.effective_chat.id, user_id=user.id)
                        break
    except Exception as e:
        logger.error(f"Error handling new member: {e}")

async def handle_message(update: Update, context: CallbackContext):
    try:
        if update.message:
            user_id = update.message.from_user.id
            chat_id = update.effective_chat.id
            
            with app.app_context():
                rules = ForceSubscribe.query.filter_by(enabled=True, check_timing='speak').all()
                if not rules:
                    return
                
                cache_key = f"{user_id}_{chat_id}"
                now = time.time()
                frequency = rules[0].verify_frequency if rules else 'per_message'
                if frequency == 'per_message' or (cache_key not in user_check_cache or now - user_check_cache[cache_key][0] > 3600):
                    is_subscribed = True
                    for rule in rules:
                        member = await context.bot.get_chat_member(chat_id=rule.target_id, user_id=user_id)
                        if member.status in (ChatMember.LEFT, ChatMember.KICKED):
                            is_subscribed = False
                            break
                    user_check_cache[cache_key] = (now, is_subscribed)
                else:
                    is_subscribed = user_check_cache[cache_key][1]
                
                if not is_subscribed:
                    await enforce_action(update, context, rules[0])
    except Exception as e:
        logger.error(f"Error handling message for subscription check: {e}")

async def enforce_action(update: Update, context: CallbackContext, rule):
    try:
        await update.message.reply_text(rule.reminder_text)
        if rule.action == 'mute':
            await context.bot.restrict_chat_member(
                chat_id=update.effective_chat.id, 
                user_id=update.message.from_user.id, 
                permissions=ChatPermissions(can_send_messages=False)
            )
            banned_users.add(update.message.from_user.id)
        elif rule.action == 'kick':
            await context.bot.ban_chat_member(chat_id=update.effective_chat.id, user_id=update.message.from_user.id)
    except Exception as e:
        logger.error(f"Error enforcing action: {e}")

async def handle_chat_member_update(update: Update, context: CallbackContext):
    try:
        if update.chat_member:
            new_member = update.chat_member.new_chat_member
            old_member = update.chat_member.old_chat_member
            user_id = new_member.user.id
            chat_id = update.effective_chat.id
            
            with app.app_context():
                auto_unmute_cfg = Config.query.filter_by(key='auto_unmute_enabled').first()
                auto_unmute = auto_unmute_cfg.value == 'True' if auto_unmute_cfg else False
                
                if not auto_unmute:
                    return
                
                if old_member.status in (ChatMember.LEFT, ChatMember.KICKED) and new_member.status == ChatMember.MEMBER:
                    rules = ForceSubscribe.query.filter_by(enabled=True).all()
                    all_subscribed = True
                    for rule in rules:
                        status = await context.bot.get_chat_member(chat_id=rule.target_id, user_id=user_id)
                        if status.status not in (ChatMember.MEMBER, ChatMember.ADMINISTRATOR, ChatMember.OWNER):
                            all_subscribed = False
                            break
                    if all_subscribed and user_id in banned_users:
                        await context.bot.restrict_chat_member(
                            chat_id=chat_id, 
                            user_id=user_id, 
                            permissions=DEFAULT_PERMISSIONS
                        )
                        unmute_msg_cfg = Config.query.filter_by(key='unmute_message').first()
                        unmute_message = unmute_msg_cfg.value if unmute_msg_cfg else '订阅完成！'
                        await context.bot.send_message(chat_id=chat_id, text=unmute_message)
                        banned_users.remove(user_id)
    except Exception as e:
        logger.error(f"Error handling chat member update: {e}")

force_subscribe_handler = ChatMemberHandler(handle_new_member, ChatMemberHandler.CHAT_MEMBER)
force_subscribe_message_handler = MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
force_subscribe_update_handler = ChatMemberHandler(handle_chat_member_update, ChatMemberHandler.ANY_CHAT_MEMBER)
