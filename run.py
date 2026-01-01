import os
import asyncio
import threading
import logging
import jwt  # 需要 pip install pyjwt
import time
from flask import Flask, request, redirect, session, url_for, render_template_string
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler
from models import db, User
from web.routes import web_bp

# --- 配置 ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

DB_URI = os.getenv('DATABASE_URL', 'sqlite:///bot.db')
if DB_URI.startswith("postgres://"):
    DB_URI = DB_URI.replace("postgres://", "postgresql://", 1)

TOKEN = os.getenv('TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_ID', 0)) # 你的 Telegram ID
SECRET_KEY = os.getenv('SECRET_KEY', 'my-super-secret-key') # 用于加密链接
PORT = int(os.getenv('PORT', 5000))
RAILWAY_URL = os.getenv('RAILWAY_PUBLIC_DOMAIN', f'http://localhost:{PORT}') # Railway会自动提供域名
if not RAILWAY_URL.startswith('http'):
    RAILWAY_URL = f"https://{RAILWAY_URL}"

# --- Flask 初始化 ---
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = DB_URI
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = SECRET_KEY

db.init_app(app)
app.register_blueprint(web_bp)

# --- 魔法登录路由 ---
@app.route('/magic_login')
def magic_login():
    token = request.args.get('token')
    if not token:
        return "无效链接", 403
    
    try:
        # 解密 Token
        payload = jwt.decode(token, SECRET_KEY, algorithms=['HS256'])
        if payload.get('user_id') == ADMIN_ID:
            session['logged_in'] = True
            return redirect('/') # 登录成功，跳转首页
        else:
            return "权限不足", 403
    except jwt.ExpiredSignatureError:
        return "链接已过期，请重新获取", 403
    except jwt.InvalidTokenError:
        return "非法链接", 403

# --- Bot 逻辑 ---
async def start(update: Update, context):
    user = update.effective_user
    # 自动入库
    with app.app_context():
        if not User.query.filter_by(telegram_id=user.id).first():
            db.session.add(User(telegram_id=user.id, username=user.username))
            db.session.commit()
    
    # 如果是管理员，显示后台按钮
    if user.id == ADMIN_ID:
        # 生成免密 Token (有效期 5 分钟)
        payload = {
            'user_id': user.id,
            'exp': time.time() + 300 
        }
        token = jwt.encode(payload, SECRET_KEY, algorithm='HS256')
        
        # 生成链接
        login_url = f"{RAILWAY_URL}/magic_login?token={token}"
        
        keyboard = [[InlineKeyboardButton("🚀 进入管理后台 (免密)", url=login_url)]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"👋 管理员 {user.first_name}，欢迎回来！\n点击下方按钮直接登录后台。",
            reply_markup=reply_markup
        )
    else:
        # 普通用户
        await update.message.reply_text(f"👋 你好 {user.first_name}！\n发送 /daka 进行打卡。")

async def daka(update: Update, context):
    # (打卡逻辑保持不变，略...)
    uid = update.effective_user.id
    with app.app_context():
        u = User.query.filter_by(telegram_id=uid).first()
        if u:
            u.points += 10
            db.session.commit()
            await update.message.reply_text(f"打卡成功！积分: {u.points}")
        else:
            await update.message.reply_text("请联系管理员注册")

# --- 启动器 ---
def run_flask():
    app.run(host='0.0.0.0', port=PORT, use_reloader=False)

async def run_bot():
    if not TOKEN: return
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("daka", daka))
    
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    
    stop_event = asyncio.Event()
    await stop_event.wait()

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    
    t = threading.Thread(target=run_flask, daemon=True)
    t.start()
    
    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        pass
