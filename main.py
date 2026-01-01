import os
import logging
import asyncio
import threading
import time
import hmac
import hashlib
from datetime import datetime, timedelta
from flask import Flask, render_template_string, request, redirect, url_for, session
from flask_sqlalchemy import SQLAlchemy
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes

# --- 配置部分 ---
DB_URI = os.getenv('DATABASE_URL', 'sqlite:///bot.db')
if DB_URI and DB_URI.startswith("postgres://"):
    DB_URI = DB_URI.replace("postgres://", "postgresql://", 1)

TOKEN = os.getenv('TOKEN')
# 必须配置 ADMIN_ID，否则机器人不知道谁是管理员
ADMIN_ID = int(os.getenv('ADMIN_ID', '0')) 
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', '123456')
PORT = int(os.getenv('PORT', 5000))
# 用于生成登录 Token 的密钥，Railway 会自动生成随机的 SECRET_KEY，如果没有就用默认的
SECRET_KEY = os.getenv('SECRET_KEY', 'my-super-secret-key-for-token')

# 获取当前 Web 的域名 (Railway 提供的域名)
# 如果你没有设置 RAILWAY_PUBLIC_DOMAIN 变量，需要手动填你的域名，否则按钮跳转会跳到 localhost
WEB_DOMAIN = os.getenv('RAILWAY_PUBLIC_DOMAIN', '') 
if not WEB_DOMAIN and os.getenv('RAILWAY_STATIC_URL'):
    WEB_DOMAIN = os.getenv('RAILWAY_STATIC_URL')

# 确保域名带 https
if WEB_DOMAIN and not WEB_DOMAIN.startswith('http'):
    WEB_DOMAIN = f"https://{WEB_DOMAIN}"

# --- 初始化 ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = DB_URI
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = SECRET_KEY
db = SQLAlchemy(app)

# --- 数据库模型 ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tg_id = db.Column(db.BigInteger, unique=True)
    username = db.Column(db.String(100))
    membership_level = db.Column(db.String(20), default='E')
    expiration_date = db.Column(db.DateTime)
    points = db.Column(db.Integer, default=0)
    last_checkin = db.Column(db.DateTime)

    @property
    def is_expired(self):
        if not self.expiration_date: return True
        return datetime.now() > self.expiration_date

# --- 工具函数：生成和验证 Token ---
def generate_login_token(admin_id):
    timestamp = int(time.time())
    data = f"{admin_id}:{timestamp}"
    signature = hmac.new(SECRET_KEY.encode(), data.encode(), hashlib.sha256).hexdigest()
    return f"{data}:{signature}"

def verify_login_token(token):
    try:
        data_part, signature = token.rsplit(':', 1)
        admin_id, timestamp = data_part.split(':')
        
        # 验证签名
        expected_signature = hmac.new(SECRET_KEY.encode(), data_part.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected_signature):
            return False
            
        # 验证是否过期 (比如 5 分钟内有效)
        if int(time.time()) - int(timestamp) > 300: 
            return False
            
        return True
    except Exception:
        return False

# --- 网页 HTML ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>管理后台</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body class="p-3">
    {% if not session.get('logged_in') %}
    <div class="container mt-5">
        <div class="alert alert-warning">请通过 Telegram 机器人发送 /start 获取登录链接，或使用密码登录。</div>
        <form method="post" action="/login">
            <input type="password" name="password" class="form-control mb-2" placeholder="密码">
            <button class="btn btn-primary">登录</button>
        </form>
    </div>
    {% else %}
    <div class="d-flex justify-content-between mb-3 align-items-center">
        <h3 class="m-0">会员管理</h3>
        <a href="/logout" class="btn btn-sm btn-outline-danger">退出</a>
    </div>
    
    <div class="card p-3 mb-4 shadow-sm">
        <h6 class="card-title">添加/续费会员</h6>
        <form method="post" action="/update_user">
            <div class="row g-2">
                <div class="col-12">
                    <input type="number" name="tg_id" class="form-control" placeholder="Telegram ID" required>
                </div>
                <div class="col-6">
                    <input type="number" name="days" class="form-control" value="30" placeholder="天数">
                </div>
                <div class="col-6">
                    <select name="level" class="form-select">
                        <option value="E">E级 (普通)</option>
                        <option value="A">A级</option>
                        <option value="B">B级</option>
                    </select>
                </div>
                <div class="col-12">
                    <button class="btn btn-success w-100">提交更新</button>
                </div>
            </div>
        </form>
    </div>

    <div class="table-responsive">
        <table class="table table-striped align-middle">
            <thead><tr><th>ID</th><th>等级</th><th>积分</th><th>过期</th></tr></thead>
            <tbody>
            {% for u in users %}
            <tr>
                <td>{{ u.tg_id }}<br><small class="text-muted">{{ u.username or '无名' }}</small></td>
                <td><span class="badge bg-secondary">{{ u.membership_level }}</span></td>
                <td>{{ u.points }}</td>
                <td>
                    {% if u.is_expired %}<span class="badge bg-danger">过期</span>
                    {% else %}<span class="badge bg-success">{{ u.expiration_date.strftime('%m-%d') }}</span>{% endif %}
                </td>
            </tr>
            {% endfor %}
            </tbody>
        </table>
    </div>
    {% endif %}
</body>
</html>
"""

# --- Flask 路由 ---
@app.route('/', methods=['GET', 'POST'])
def index():
    if not session.get('logged_in'): return render_template_string(HTML_TEMPLATE)
    users = User.query.order_by(User.id.desc()).all()
    return render_template_string(HTML_TEMPLATE, users=users, session=session)

@app.route('/login', methods=['POST'])
def login():
    if request.form.get('password') == ADMIN_PASSWORD: session['logged_in'] = True
    return redirect('/')

# --- 新增：魔法登录路由 ---
@app.route('/magic_login')
def magic_login():
    token = request.args.get('token')
    if token and verify_login_token(token):
        session['logged_in'] = True
        return redirect('/')
    return "登录链接无效或已过期", 403

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect('/')

@app.route('/update_user', methods=['POST'])
def update_user():
    if not session.get('logged_in'): return redirect('/')
    tg_id = int(request.form.get('tg_id'))
    days = int(request.form.get('days', 0))
    level = request.form.get('level')
    
    user = User.query.filter_by(tg_id=tg_id).first()
    if not user:
        user = User(tg_id=tg_id)
        db.session.add(user)
    
    now = datetime.now()
    if user.expiration_date and user.expiration_date > now:
        user.expiration_date += timedelta(days=days)
    else:
        user.expiration_date = now + timedelta(days=days)
    
    user.membership_level = level
    db.session.commit()
    return redirect('/')

# --- Bot 逻辑 ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    tg_id = u.id

    # 自动入库逻辑
    with app.app_context():
        if not User.query.filter_by(tg_id=tg_id).first():
            db.session.add(User(tg_id=tg_id, username=u.username))
            db.session.commit()
    
    # --- 管理员特殊回复 ---
    if tg_id == ADMIN_ID:
        if not WEB_DOMAIN:
            await update.message.reply_text("⚠️ 请先在 Railway 变量中设置 RAILWAY_PUBLIC_DOMAIN，否则无法生成跳转链接。")
            return

        # 生成免密登录 Token
        token = generate_login_token(tg_id)
        login_url = f"{WEB_DOMAIN}/magic_login?token={token}"
        
        keyboard = [[InlineKeyboardButton("🚀 进入管理后台 (免密)", url=login_url)]]
        await update.message.reply_text(
            f"👋 管理员 {u.first_name}，你好！\n\n点击下方按钮可直接登录后台管理用户。",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        # 普通用户回复
        await update.message.reply_text(f"👋 欢迎 {u.first_name}\n/daka - 打卡\n/me - 我的状态")

async def daka(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_id = update.effective_user.id
    now = datetime.now()
    with app.app_context():
        user = User.query.filter_by(tg_id=tg_id).first()
        if not user: return await update.message.reply_text("⚠️ 请先联系管理员开通！")
        if user.is_expired: return await update.message.reply_text("❌ 会员已过期！")
        if user.last_checkin and user.last_checkin.date() == now.date():
            return await update.message.reply_text("📅 今天已打卡！")
        
        user.last_checkin = now
        user.points += 10
        db.session.commit()
        await update.message.reply_text(f"✅ 打卡成功！积分+10\n当前积分：{user.points}")

async def my_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with app.app_context():
        user = User.query.filter_by(tg_id=update.effective_user.id).first()
        if not user: return await update.message.reply_text("无信息")
        status = "过期" if user.is_expired else "正常"
        date = user.expiration_date.strftime('%Y-%m-%d') if user.expiration_date else "无"
        await update.message.reply_text(f"ID: {user.tg_id}\n等级: {user.membership_level}\n状态: {status}\n到期: {date}\n积分: {user.points}")

# --- 核心启动逻辑 ---
def run_flask():
    app.run(host='0.0.0.0', port=PORT, use_reloader=False)

async def main():
    with app.app_context():
        db.create_all()

    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    logger.info(f"🌐 Flask Web running on port {PORT}")

    if not TOKEN: return

    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("daka", daka))
    application.add_handler(CommandHandler("me", my_info))

    logger.info("🤖 Bot starting...")
    
    await application.initialize()
    await application.start()
    await application.updater.start_polling(allowed_updates=Update.ALL_TYPES)

    stop_event = asyncio.Event()
    await stop_event.wait()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
