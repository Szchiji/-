from flask import Flask, render_template, request, redirect, url_for
from config import Config
from models import db, User, AutoReply

app = Flask(__name__)
app.config.from_object(Config)

# 初始化数据库
db.init_app(app)

@app.route('/')
def index():
    users = User.query.all()
    return render_template('index.html', users=users)

@app.route('/add_reply', methods=['POST'])
def add_reply():
    keyword = request.form.get('keyword')
    content = request.form.get('content')
    if keyword and content:
        rule = AutoReply(keyword=keyword, reply_content=content, match_type='contains')
        db.session.add(rule)
        db.session.commit()
    return redirect(url_for('index'))

# 创建数据库表（仅用于初次运行）
def init_db():
    with app.app_context():
        db.create_all()

if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=5000)
