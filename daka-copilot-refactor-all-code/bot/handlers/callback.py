from telegram import Update
from telegram.ext import CallbackQueryHandler, CallbackContext
import logging

async def handle_callback_query(update: Update, context: CallbackContext):
    query = update.callback_query
    try:
        await query.answer()
        data = query.data
        if data == 'confirm':
            await query.edit_message_text(text='已确认！操作完成。')
        elif data == 'cancel':
            await query.edit_message_text(text='操作取消。')
        # 其他逻辑...
    except Exception as e:
        logging.error(f"Callback error: {e}")
        await query.answer(text='处理失败，请重试。', show_alert=True)

callback_handler = CallbackQueryHandler(handle_callback_query)
