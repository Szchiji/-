import os
import asyncio
import threading
import logging
import jwt
import time
from datetime import datetime, timedelta
from flask import Flask, request, redirect, session, url_for, render_template_string
from flask_sqlalchemy import SQLAlchemy
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- 1. 配置部分 ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# 处理 Railway 数据库地址格式
DB_URI = os.getenv('DATABASE_URL', 'sqlite:///bot.db')
if DB_URI.startswith("postgres://"):
    DB_URI = DB_URI.replace("postgres://", "postgresql://", 1)

TOKEN = os.getenv('TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_ID', 0))
SECRET_KEY = os.getenv('SECRET_KEY', 'my-super-secret-key')
PORT = int(os.getenv('PORT', 5000))

# 获取外部域名 (用于生成免密登录链接)
RAILWAY_URL = os.getenv('RAILWAY_PUBLIC_DOMAIN', '')
if not RAILWAY_URL and os.getenv('RAILWAY_STATIC_URL'):
    RAILWAY_URL = os.getenv('RAILWAY_STATIC_URL')
if RAILWAY_URL and not RAILWAY_URL.startswith('http'):
    RAILWAY_URL = f"https://{RAILWAY_URL}"

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = DB_URI
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = SECRET_KEY
db = SQLAlchemy(app)

# 全局变量，用于在 Flask 中调用 Bot 发送广播
global_bot = None
bot_loop = None

# --- 2. 数据库模型 (全功能版) ---
class User(db.Model):
    # 【关键】修改表名，强制创建新表，解决字段缺失报错
    __tablename__ = 'users_v4' 
    
    id = db.Column(db.Integer, primary_key=True)
    tg_id = db.Column(db.BigInteger, unique=True, index=True)
    username = db.Column(db.String(100))
    
    # 核心业务字段 (完整还原)
    membership_id = db.Column(db.String(50))    # 会员ID
    training_title = db.Column(db.String(100))  # 培训头衔
    price = db.Column(db.String(50))            # 价格
    region = db.Column(db.String(50))           # 地区
    level = db.Column(db.String(20), default='E') # 等级
    image_url = db.Column(db.String(255))       # 图片链接
    
    # 状态字段
    expiration_date = db.Column(db.DateTime)
    points = db.Column(db.Integer, default=0)
    checkin_time = db.Column(db.DateTime)
    online = db.Column(db.Boolean, default=False)

    @property
    def is_expired(self):
        if not self.expiration_date: return True
        return datetime.now() > self.expiration_date

class AutoReply(db.Model):
    __tablename__ = 'auto_replies_v2'
    id = db.Column(db.Integer, primary_key=True)
    keyword = db.Column(db.String(100), nullable=False)
    reply_text = db.Column(db.Text, nullable=False)

# --- 3. 网页后台 (增强版) ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Bot 管理后台</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        .nav-tabs .nav-link.active { font-weight: bold; border-bottom: 3px solid #0d6efd; }
    </style>
</head>
<body class="bg-light p-3">
    {% if not session.get('logged_in') %}
    <div class="container mt-5 text-center">
        <h3>请通过机器人发送 /start 获取登录链接</h3>
    </div>
    {% else %}
    <div class="container bg-white p-4 rounded shadow-sm">
        <div class="d-flex justify-content-between mb-4">
            <h3>🎛️ 机器人控制台</h3>
            <a href="/logout" class="btn btn-outline-danger btn-sm">退出</a>
        </div>

        <ul class="nav nav-tabs mb-4">
            <li class="nav-item"><a class="nav-link {{ 'active' if tab=='users' else '' }}" href="/?tab=users">👥 会员管理</a></li>
            <li class="nav-item"><a class="nav-link {{ 'active' if tab=='reply' else '' }}" href="/?tab=reply">🤖 自动回复</a></li>
            <li class="nav-item"><a class="nav-link {{ 'active' if tab=='broadcast' else '' }}" href="/?tab=broadcast">📢 群发广播</a></li>
        </ul>

        {% if tab == 'users' %}
        <!-- 用户管理 -->
        <div class="card mb-4">
            <div class="card-header">添加 / 修改会员</div>
            <div class="card-body">
                <form method="post" action="/update_user">
                    <div class="row g-2">
                        <div class="col-md-3"><input type="number" name="tg_id" class="form-control" placeholder="Telegram ID (必填)" required></div>
                        <div class="col-md-3"><input type="text" name="training_title" class="form-control" placeholder="头衔 (如: 英语老师)"></div>
                        <div class="col-md-2"><input type="text" name="price" class="form-control" placeholder="价格 (如: 500P)"></div>
                        <div class="col-md-2"><input type="text" name="region" class="form-control" placeholder="地区"></div>
                        <div class="col-md-2">
                            <select name="level" class="form-select">
                                <option value="E">E级</option><option value="A">A级</option><option value="B">B级</option>
                            </select>
                        </div>
                        <div class="col-md-3"><input type="number" name="days" class="form-control" value="30" placeholder="续费天数"></div>
                        <div class="col-md-3"><button class="btn btn-success w-100">保存</button></div>
                    </div>
                </form>
            </div>
        </div>
        <div class="table-responsive">
            <table class="table table-hover align-middle">
                <thead class="table-light"><tr><th>ID / 用户</th><th>头衔 / 价格</th><th>过期时间</th><th>状态</th><th>操作</th></tr></thead>
                <tbody>
                {% for u in users %}
                <tr>
                    <td>{{ u.tg_id }}<br><small class="text-muted">{{ u.username or '无名' }}</small></td>
                    <td><span class="fw-bold">{{ u.training_title or '-' }}</span><br><small>{{ u.price or '-' }} | {{ u.region or '-' }}</small></td>
                    <td>
                        {% if u.is_expired %}<span class="badge bg-danger">已过期</span>
                        {% else %}<span class="badge bg-success">{{ u.expiration_date.strftime('%Y-%m-%d') }}</span>{% endif %}
                    </td>
                    <td>{{ '🟢' if u.online else '⚪️' }}</td>
                    <td><a href="/delete_user/{{ u.id }}" class="btn btn-sm btn-outline-danger" onclick="return confirm('确定删除？')">删除</a></td>
                </tr>
                {% endfor %}
                </tbody>
            </table>
        </div>

        {% elif tab == 'reply' %}
        <!-- 自动回复 -->
        <div class="row">
            <div class="col-md-4">
                <form action="/add_reply" method="POST" class="card p-3">
                    <div class="mb-2"><input type="text" name="keyword" class="form-control" placeholder="关键词" required></div>
                    <div class="mb-2"><textarea name="reply_text" class="form-control" placeholder="回复内容" rows="3" required></textarea></div>
                    <button class="btn btn-primary w-100">添加规则</button>
                </form>
            </div>
            <div class="col-md-8">
                <table class="table bg-white border">
                    {% for r in replies %}
                    <tr><td>{{ r.keyword }}</td><td>{{ r.reply_text }}</td><td><a href="/del_reply/{{ r.id }}" class="text-danger">删除</a></td></tr>
                    {% endfor %}
                </table>
            </div>
        </div>
        
        {% elif tab == 'broadcast' %}
        <!-- 广播 -->
        <div class="card">
            <div class="card-body text-center">
                <h5>📢 全员群发消息</h5>
                <p>消息将发送给数据库中所有用户。</p>
                <form action="/broadcast" method="POST">
                    <textarea name="msg" class="form-control mb-3" rows="4" placeholder="在此输入广播内容..." required></textarea>
                    <button class="btn btn-warning w-50">🚀 发送广播</button>
                </form>
            </div>
        </div>
        {% endif %}
    </div>
    {% endif %}
</body>
</html>
"""

# --- Flask 路由 ---
@app.route('/')
def index():
    if not session.get('logged_in'): return render_template_string(HTML_TEMPLATE)
    tab = request.args.get('tab', 'users')
    
    users = []
    replies = []
    
    if tab == 'users':
        users = User.query.order_by(User.id.desc()).all()
    elif tab == 'reply':
        replies = AutoReply.query.all()
        
    return render_template_string(HTML_TEMPLATE, users=users, replies=replies, tab=tab, session=session)

@app.route('/magic_login')
def magic_login():
    token = request.args.get('token')
    if not token: return "Link invalid", 403
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=['HS256'])
        if payload.get('user_id') == ADMIN_ID:
            session['logged_in'] = True
            return redirect('/?tab=users')
    except: pass
    return "链接无效或已过期", 403

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect('/')

@app.route('/update_user', methods=['POST'])
def update_user():
    if not session.get('logged_in'): return redirect('/')
    tg_id = int(request.form.get('tg_id'))
    
    user = User.query.filter_by(tg_id=tg_id).first()
    if not user:
        user = User(tg_id=tg_id)
        db.session.add(user)
    
    # 更新所有字段
    user.training_title = request.form.get('training_title')
    user.price = request.form.get('price')
    user.region = request.form.get('region')
    user.level = request.form.get('level')
    
    # 续费逻辑
    days = int(request.form.get('days', 0))
    now = datetime.now()
    if user.expiration_date and user.expiration_date > now:
        user.expiration_date += timedelta(days=days)
    else:
        user.expiration_date = now + timedelta(days=days)
        
    db.session.commit()
    return redirect('/?tab=users')

@app.route('/delete_user/<int:id>')
def delete_user(id):
    if not session.get('logged_in'): return redirect('/')
    User.query.filter_by(id=id).delete()
    db.session.commit()
    return redirect('/?tab=users')

@app.route('/add_reply', methods=['POST'])
def add_reply():
    if not session.get('logged_in'): return redirect('/')
    db.session.add(AutoReply(keyword=request.form.get('keyword'), reply_text=request.form.get('reply_text')))
    db.session.commit()
    return redirect('/?tab=reply')

@app.route('/del_reply/<int:id>')
def del_reply(id):
    if not session.get('logged_in'): return redirect('/')
    AutoReply.query.filter_by(id=id).delete()
    db.session.commit()
    return redirect('/?tab=reply')

@app.route('/broadcast', methods=['POST'])
def broadcast():
    if not session.get('logged_in'): return redirect('/')
    msg = request.form.get('msg')
    
    # 简单的后台线程发送广播
    def send_bg():
        with app.app_context():
            users = User.query.all()
            for u in users:
                try:
                    if global_bot and bot_loop:
                        # 线程安全调用
                        asyncio.run_coroutine_threadsafe(
                            global_bot.send_message(chat_id=u.tg_id, text=f"📢 <b>系统通知</b>\n\n{msg}", parse_mode='HTML'),
                            bot_loop
                        )
                except: pass
    
    threading.Thread(target=send_bg).start()
    return redirect('/?tab=broadcast')

# --- 4. Bot 逻辑 (完整版) ---
async def start(update: Update, context):
    user = update.effective_user
    with app.app_context():
        if not User.query.filter_by(tg_id=user.id).first():
            db.session.add(User(tg_id=user.id, username=user.username))
            db.session.commit()
    
    if user.id == ADMIN_ID:
        if not RAILWAY_URL:
            await update.message.reply_text("⚠️ 请检查 RAILWAY_PUBLIC_DOMAIN 变量！")
            return
        payload = {'user_id': user.id, 'exp': time.time() + 600}
        token = jwt.encode(payload, SECRET_KEY, algorithm='HS256')
        url = f"{RAILWAY_URL}/magic_login?token={token}"
        await update.message.reply_text("👋 管理员后台：", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🚀 点击登录后台", url=url)]]))
    else:
        await update.message.reply_text("👋 欢迎使用！\n\n🔹 /daka - 每日打卡\n🔹 /online - 在线列表")

async def daka(update: Update, context):
    uid = update.effective_user.id
    now = datetime.now()
    with app.app_context():
        u = User.query.filter_by(tg_id=uid).first()
        if not u: return await update.message.reply_text("⚠️ 你还不是会员，请联系管理员开通。")
        if u.is_expired: return await update.message.reply_text("❌ 您的会员已过期，请续费。")
        
        # 允许重复打卡更新时间，但积分每天只加一次
        if u.last_checkin and u.last_checkin.date() == now.date():
            pass 
        else:
            u.points += 10
            
        u.last_checkin = now
        u.online = True
        db.session.commit()
        
        # 还原原版的详细回复格式
        title = u.training_title or "普通会员"
        price = u.price or "暂无价格"
        msg = f"✅ <b>打卡成功！</b>\n\n👤 身份：{title}\n💰 价格：{price}\n🏆 积分：{u.points}\n🟢 状态：在线"
        
        # 如果有设置图片则发图，否则发文字
        if u.image_url:
            try:
                await update.message.reply_photo(photo=u.image_url, caption=msg, parse_mode='HTML')
            except:
                await update.message.reply_text(msg, parse_mode='HTML')
        else:
            await update.message.reply_text(msg, parse_mode='HTML')

async def online(update: Update, context):
    with app.app_context():
        # 查找最近 24 小时打卡的人
        yesterday = datetime.now() - timedelta(days=1)
        users = User.query.filter(User.checkin_time >= yesterday).order_by(User.checkin_time.desc()).all()
        
        if not users: return await update.message.reply_text("😢 暂无在线用户")
        
        msg = "📋 <b>实时在线列表</b>\n\n"
        for u in users:
            # 格式：🟢 [头衔] 名字 价格
            title = u.training_title or "会员"
            price = u.price or ""
            name = u.username or str(u.tg_id)
            msg += f"🟢 {title} | {name} {price}\n"
        
        await update.message.reply_text(msg, parse_mode='HTML')

async def handle_message(update: Update, context):
    text = update.message.text
    if not text: return
    
    # 自动回复逻辑
    with app.app_context():
        # 简单包含匹配
        rules = AutoReply.query.all()
        for r in rules:
            if r.keyword in text:
                await update.message.reply_text(r.reply_text)
                return

# --- 启动器 ---
def run_flask():
    app.run(host='0.0.0.0', port=PORT, use_reloader=False)

async def run_bot():
    global global_bot
    if not TOKEN: return
    application = Application.builder().token(TOKEN).build()
    global_bot = application.bot # 赋值给全局变量
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("daka", daka))
    application.add_handler(CommandHandler("online", online))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    
    stop_event = asyncio.Event()
    await stop_event.wait()

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    
    # 启动 Flask 线程
    t = threading.Thread(target=run_flask, daemon=True)
    t.start()
    
    # 启动 Bot 循环
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        bot_loop = loop # 保存 loop 给广播用
        loop.run_until_complete(run_bot())
    except KeyboardInterrupt:
        pass
