import os
import logging
import threading
import asyncio
from datetime import datetime
from flask import Flask, request, render_template_string, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- 配置 ---
TOKEN = os.getenv('TOKEN')  # 在 Railway 变量里填
ADMIN_ID = os.getenv('ADMIN_ID') # 你的 ID
PORT = int(os.getenv('PORT', 5000))

# --- 初始化 Flask 和 数据库 ---
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///bot.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# --- 数据库模型 ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tg_id = db.Column(db.BigInteger, unique=True)
    username = db.Column(db.String(100))
    points = db.Column(db.Integer, default=0)
    level = db.Column(db.String(20), default='E') # 等级
    checkin_time = db.Column(db.DateTime) # 最后打卡时间
    is_online = db.Column(db.Boolean, default=False)
    expiration_date = db.Column(db.String(20)) # 过期日期 (字符串格式 YYYY-MM-DD)

class AutoReply(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    keyword = db.Column(db.String(100))
    reply = db.Column(db.String(500))

# 创建数据库表
with app.app_context():
    db.create_all()

# --- 机器人逻辑 ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("机器人已启动！发送 /daka 打卡，发送 /online 查询在线用户。")

async def daka(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_id = update.effective_user.id
    username = update.effective_user.username or "无名氏"
    
    with app.app_context():
        user = User.query.filter_by(tg_id=tg_id).first()
        if not user:
            user = User(tg_id=tg_id, username=username)
            db.session.add(user)
        
        user.checkin_time = datetime.now()
        user.is_online = True
        user.points += 10
        current_points = user.points
        db.session.commit()
    
    await update.message.reply_text(f"✅ 打卡成功！\n积分：{current_points}\n状态：🟢 在线")

async def online(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with app.app_context():
        # 简单逻辑：只要打过卡就算在线 (你可以加时间判断)
        users = User.query.filter_by(is_online=True).all()
        msg = "📋 **在线用户列表**\n"
        for u in users:
            msg += f"🟢 {u.username} | {u.level}级 | {u.points}分\n"
    
    await update.message.reply_text(msg or "暂无在线用户")

async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if not text: return
    
    with app.app_context():
        rules = AutoReply.query.all()
        for rule in rules:
            if rule.keyword in text:
                await update.message.reply_text(rule.reply)
                return

# --- 网页后台 (HTML 模板嵌入) ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Bot 管理后台</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body class="p-3">
    <h2>👥 用户管理</h2>
    <table class="table table-striped">
        <tr><th>ID</th><th>名字</th><th>积分</th><th>等级</th><th>过期时间</th><th>操作</th></tr>
        {% for user in users %}
        <tr>
            <td>{{ user.tg_id }}</td>
            <td>{{ user.username }}</td>
            <td>{{ user.points }}</td>
            <td>{{ user.level }}</td>
            <td>{{ user.expiration_date or '永久' }}</td>
            <td>
                <a href="/delete/{{ user.id }}" class="btn btn-danger btn-sm">删除</a>
            </td>
        </tr>
        {% endfor %}
    </table>
    
    <hr>
    
    <h2>🤖 自动回复设置</h2>
    <form action="/add_rule" method="POST" class="mb-3">
        <input type="text" name="keyword" placeholder="关键词" class="form-control mb-2" required>
        <input type="text" name="reply" placeholder="回复内容" class="form-control mb-2" required>
        <button type="submit" class="btn btn-primary">添加规则</button>
    </form>
    <ul>
        {% for rule in rules %}
        <li>关键词: <b>{{ rule.keyword }}</b> -> 回复: {{ rule.reply }} <a href="/del_rule/{{ rule.id }}">❌</a></li>
        {% endfor %}
    </ul>
</body>
</html>
"""

@app.route('/')
def index():
    users = User.query.all()
    rules = AutoReply.query.all()
    return render_template_string(HTML_TEMPLATE, users=users, rules=rules)

@app.route('/add_rule', methods=['POST'])
def add_rule():
    keyword = request.form.get('keyword')
    reply = request.form.get('reply')
    db.session.add(AutoReply(keyword=keyword, reply=reply))
    db.session.commit()
    return redirect('/')

@app.route('/del_rule/<int:id>')
def del_rule(id):
    AutoReply.query.filter_by(id=id).delete()
    db.session.commit()
    return redirect('/')

@app.route('/delete/<int:id>')
def delete_user(id):
    User.query.filter_by(id=id).delete()
    db.session.commit()
    return redirect('/')

# --- 启动逻辑 (多线程) ---
def run_bot():
    # 建立 Bot 应用
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("daka", daka))
    application.add_handler(CommandHandler("online", online))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
    
    # 启动 Polling
    asyncio.set_event_loop(asyncio.new_event_loop())
    application.run_polling()

if __name__ == '__main__':
    # 在后台线程启动机器人
    if TOKEN:
        t = threading.Thread(target=run_bot)
        t.start()
    
    # 在主线程启动网页
    app.run(host='0.0.0.0', port=PORT)
