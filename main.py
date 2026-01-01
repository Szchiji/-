import os
import logging
import asyncio
import threading
from datetime import datetime, timedelta
from flask import Flask, render_template_string, request, redirect, url_for, session
from flask_sqlalchemy import SQLAlchemy
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# --- 配置部分 ---
# Railway 的 DATABASE_URL 默认为 postgres://，需要修正为 postgresql:// 才能被 SQLAlchemy 识别
DB_URI = os.getenv('DATABASE_URL', 'sqlite:///bot.db')
if DB_URI and DB_URI.startswith("postgres://"):
    DB_URI = DB_URI.replace("postgres://", "postgresql://", 1)

TOKEN = os.getenv('TOKEN')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', '123456')
PORT = int(os.getenv('PORT', 5000))

# --- 初始化 ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = DB_URI
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.urandom(24)
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
    <form method="post" action="/login" class="mt-5">
        <h3>管理员登录</h3>
        <input type="password" name="password" class="form-control mb-2" placeholder="密码">
        <button class="btn btn-primary">登录</button>
    </form>
    {% else %}
    <div class="d-flex justify-content-between mb-3">
        <h3>会员管理</h3><a href="/logout" class="btn btn-sm btn-danger">退出</a>
    </div>
    <form method="post" action="/update_user" class="card p-3 mb-3">
        <h6>添加/续费</h6>
        <input type="number" name="tg_id" class="form-control mb-2" placeholder="Telegram ID" required>
        <input type="number" name="days" class="form-control mb-2" value="30" placeholder="天数">
        <select name="level" class="form-control mb-2">
            <option value="E">E级 (普通)</option>
            <option value="A">A级</option>
            <option value="B">B级</option>
        </select>
        <button class="btn btn-success w-100">提交</button>
    </form>
    <table class="table table-sm">
        <thead><tr><th>ID</th><th>等级</th><th>积分</th><th>过期</th></tr></thead>
        <tbody>
        {% for u in users %}
        <tr>
            <td>{{ u.tg_id }}</td>
            <td>{{ u.membership_level }}</td>
            <td>{{ u.points }}</td>
            <td>
                {% if u.is_expired %}<span class="badge bg-danger">过期</span>
                {% else %}<span class="badge bg-success">{{ u.expiration_date.strftime('%m-%d') }}</span>{% endif %}
            </td>
        </tr>
        {% endfor %}
        </tbody>
    </table>
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
    with app.app_context():
        if not User.query.filter_by(tg_id=u.id).first():
            db.session.add(User(tg_id=u.id, username=u.username))
            db.session.commit()
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
    # 在独立线程启动 Flask，use_reloader=False 防止重复启动
    app.run(host='0.0.0.0', port=PORT, use_reloader=False)

async def main():
    # 1. 确保数据库表存在
    with app.app_context():
        db.create_all()

    # 2. 启动 Flask 线程 (后台)
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    logger.info(f"🌐 Flask Web running on port {PORT}")

    # 3. 启动 Bot (主线程)
    if not TOKEN:
        logger.error("❌ 未设置 BOT_TOKEN")
        return

    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("daka", daka))
    application.add_handler(CommandHandler("me", my_info))

    logger.info("🤖 Bot starting...")
    
    # 手动控制循环，解决信号冲突
    await application.initialize()
    await application.start()
    await application.updater.start_polling(allowed_updates=Update.ALL_TYPES)

    # 保持运行
    stop_event = asyncio.Event()
    await stop_event.wait()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
