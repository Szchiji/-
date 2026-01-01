import os
import asyncio
import threading
import logging
import jwt
import time
import json
import re
from datetime import datetime, timedelta
from flask import Flask, request, redirect, session, render_template_string
from flask_sqlalchemy import SQLAlchemy
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- 配置 ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

DB_URI = os.getenv('DATABASE_URL', 'sqlite:///bot.db')
if DB_URI.startswith("postgres://"):
    DB_URI = DB_URI.replace("postgres://", "postgresql://", 1)

TOKEN = os.getenv('TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_ID', 0))
SECRET_KEY = os.getenv('SECRET_KEY', 'secret')
PORT = int(os.getenv('PORT', 5000))
RAILWAY_URL = os.getenv('RAILWAY_PUBLIC_DOMAIN', '')
if RAILWAY_URL and not RAILWAY_URL.startswith('http'): RAILWAY_URL = f"https://{RAILWAY_URL}"

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = DB_URI
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = SECRET_KEY
db = SQLAlchemy(app)

# --- 数据库模型 ---
class Config(db.Model):
    """存储所有配置：字段定义、消息模板、系统开关"""
    key = db.Column(db.String(50), primary_key=True)
    value = db.Column(db.Text)

class User(db.Model):
    __tablename__ = 'users_v6' # 升级表名
    id = db.Column(db.Integer, primary_key=True)
    tg_id = db.Column(db.BigInteger, unique=True, index=True)
    username = db.Column(db.String(100))
    profile_data = db.Column(db.Text, default='{}') # 动态字段存JSON
    expiration_date = db.Column(db.DateTime)
    points = db.Column(db.Integer, default=0)
    checkin_time = db.Column(db.DateTime)
    online = db.Column(db.Boolean, default=False)
    
    @property
    def is_expired(self):
        if not self.expiration_date: return True
        return datetime.now() > self.expiration_date

# --- 默认初始配置 ---
DEFAULT_FIELDS = [
    {"key": "name", "label": "老师名字", "type": "text"},
    {"key": "link", "label": "老师链接", "type": "text"},
    {"key": "cup", "label": "罩杯", "type": "select", "options": "A,B,C,D,E,F"},
    {"key": "price", "label": "价格", "type": "text"},
    {"key": "region", "label": "地区", "type": "select", "options": "北京,上海,广州,深圳"},
    {"key": "tags", "label": "类型", "type": "checkbox", "options": "短发,女友感,上门,69"}
]
# 默认系统设置 (对应截图2/6)
DEFAULT_SYSTEM = {
    "checkin_open": True,
    "checkin_cmd": "/daka",
    "query_open": True,
    "query_cmd": "/online",
    "online_emoji": "🟢",
    "offline_emoji": "🔴",
    "page_size": 10
}
DEFAULT_TEMPLATE = "<b>{onlineEmoji} {老师名字}</b> | <a href='{老师链接}'>点击联系</a>\n💰 价格：{价格}\n👙 罩杯：{罩杯}\n📍 地区：{地区}\n🏷 类型：{类型}"

# --- 辅助函数 ---
def get_conf(key, default):
    c = Config.query.filter_by(key=key).first()
    return json.loads(c.value) if c else default

def set_conf(key, value):
    c = Config.query.filter_by(key=key).first()
    if not c:
        c = Config(key=key)
        db.session.add(c)
    c.value = json.dumps(value, ensure_ascii=False)
    db.session.commit()

# --- 网页后台 ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>阿福Bot管理后台</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <!-- 引入 TinyMCE 富文本编辑器 (还原截图1) -->
    <script src="https://cdn.tiny.cloud/1/no-api-key/tinymce/6/tinymce.min.js" referrerpolicy="origin"></script>
    <style>
        body { background-color: #f4f6f9; }
        .sidebar { background: #fff; height: 100vh; position: fixed; width: 240px; border-right: 1px solid #e1e4e8; padding-top: 20px; overflow-y: auto; }
        .content { margin-left: 240px; padding: 25px; }
        .nav-link { color: #555; padding: 12px 20px; display: block; text-decoration: none; border-left: 4px solid transparent; }
        .nav-link:hover, .nav-link.active { background: #f0f7ff; color: #007bff; border-left-color: #007bff; font-weight: 500; }
        .card { border: none; box-shadow: 0 2px 12px rgba(0,0,0,0.04); border-radius: 8px; margin-bottom: 20px; }
        .card-header { background: #fff; border-bottom: 1px solid #f0f0f0; font-weight: 600; padding: 18px 25px; font-size: 16px; }
        .section-title { font-size: 12px; color: #999; padding: 10px 20px 5px; text-transform: uppercase; letter-spacing: 1px; }
        .color-dot { display:inline-block; width:12px; height:12px; border-radius:50%; margin-right:5px; }
    </style>
</head>
<body>
    {% if not session.get('logged_in') %}
    <div class="d-flex justify-content-center align-items-center" style="height: 100vh;">
        <div class="card p-5 text-center shadow">
            <h4>🔐 管理员登录</h4>
            <p class="text-muted mt-2">请在 Telegram 发送 /start 获取登录链接</p>
        </div>
    </div>
    {% else %}
    
    <div class="sidebar">
        <h4 class="px-4 mb-3" style="color:#007bff">阿福Bot</h4>
        
        <div class="section-title">认证用户</div>
        <a href="/?tab=users" class="nav-link {{ 'active' if tab=='users' else '' }}">👤 认证用户列表</a>
        <a href="/?tab=fields" class="nav-link {{ 'active' if tab=='fields' else '' }}">🛠 认证用户配置</a>
        
        <div class="section-title">查询与打卡</div>
        <a href="/?tab=system" class="nav-link {{ 'active' if tab=='system' else '' }}">⚙️ 打卡与查询配置</a>
        <a href="/?tab=template" class="nav-link {{ 'active' if tab=='template' else '' }}">📝 消息模板配置</a>

        <div class="mt-5 px-4">
            <a href="/logout" class="btn btn-outline-danger w-100">退出登录</a>
        </div>
    </div>

    <div class="content">
        <!-- 1. 系统配置 (还原截图 2, 6) -->
        {% if tab == 'system' %}
        <div class="card">
            <div class="card-header">⚙️ 打卡与查询配置 (System Config)</div>
            <div class="card-body">
                <form method="post" action="/save_system">
                    <div class="row mb-4">
                        <div class="col-md-6">
                            <h6 class="mb-3 text-primary">打卡配置 (Check-in)</h6>
                            <div class="form-check form-switch mb-3">
                                <input class="form-check-input" type="checkbox" name="checkin_open" {{ 'checked' if sys.checkin_open }}>
                                <label class="form-check-label">开启打卡 (Open Check-in)</label>
                            </div>
                            <div class="mb-3">
                                <label>打卡指令 (Command)</label>
                                <input type="text" name="checkin_cmd" class="form-control" value="{{ sys.checkin_cmd }}">
                            </div>
                        </div>
                        <div class="col-md-6">
                            <h6 class="mb-3 text-primary">查询配置 (Query)</h6>
                            <div class="form-check form-switch mb-3">
                                <input class="form-check-input" type="checkbox" name="query_open" {{ 'checked' if sys.query_open }}>
                                <label class="form-check-label">开启查询在线 (Open Query)</label>
                            </div>
                            <div class="mb-3">
                                <label>查询在线指令 (Command)</label>
                                <input type="text" name="query_cmd" class="form-control" value="{{ sys.query_cmd }}">
                            </div>
                        </div>
                    </div>
                    <hr>
                    <div class="row mb-3">
                        <div class="col-md-4">
                            <label>在线表情 (Online Emoji)</label>
                            <input type="text" name="online_emoji" class="form-control" value="{{ sys.online_emoji }}">
                        </div>
                        <div class="col-md-4">
                            <label>离线表情 (Offline Emoji)</label>
                            <input type="text" name="offline_emoji" class="form-control" value="{{ sys.offline_emoji }}">
                        </div>
                        <div class="col-md-4">
                            <label>每页显示数量 (Page Size)</label>
                            <input type="number" name="page_size" class="form-control" value="{{ sys.page_size }}">
                        </div>
                    </div>
                    <button class="btn btn-primary">💾 保存配置</button>
                </form>
            </div>
        </div>

        <!-- 2. 消息模板 (还原截图 1, 5) -->
        {% elif tab == 'template' %}
        <div class="card">
            <div class="card-header">📝 查询在线用户模板</div>
            <div class="card-body">
                <p class="text-muted mb-2">点击下方标签插入变量：</p>
                <div class="mb-3">
                    <span class="badge bg-info me-2 cursor-pointer" onclick="insert('{onlineEmoji}')">{在线表情}</span>
                    {% for f in fields %}
                    <span class="badge bg-secondary me-2 cursor-pointer" onclick="insert('{'+'{{ f.label }}'+'}')">{ {{ f.label }} }</span>
                    {% endfor %}
                </div>
                
                <form method="post" action="/save_template">
                    <!-- 富文本编辑器 -->
                    <textarea id="myEditor" name="template" rows="10">{{ template_str }}</textarea>
                    <button class="btn btn-success mt-3">💾 保存模板</button>
                </form>
                <script>
                    tinymce.init({
                        selector: '#myEditor',
                        height: 300,
                        plugins: 'link code',
                        toolbar: 'undo redo | bold italic forecolor backcolor | link | code',
                        menubar: false
                    });
                    function insert(tag) {
                        tinymce.activeEditor.insertContent(tag);
                    }
                </script>
            </div>
        </div>

        <!-- 3. 字段配置 (还原截图 4) -->
        {% elif tab == 'fields' %}
        <div class="card">
            <div class="card-header">🛠 认证用户配置 (Fields Config)</div>
            <div class="card-body">
                <div class="alert alert-warning">
                    这里定义了用户资料包含哪些字段。格式为 JSON 数组。<br>
                    支持类型：<code>text</code>, <code>select</code>, <code>checkbox</code>, <code>textarea</code>
                </div>
                <form method="post" action="/save_fields">
                    <textarea name="fields_json" class="form-control" rows="15" style="font-family: monospace;">{{ fields_json }}</textarea>
                    <button class="btn btn-primary mt-3">💾 保存字段定义</button>
                </form>
            </div>
        </div>

        <!-- 4. 用户列表 (还原截图 3) -->
        {% else %}
        <div class="d-flex justify-content-between align-items-center mb-4">
            <h4 class="m-0">认证用户列表</h4>
            <button class="btn btn-primary" data-bs-toggle="modal" data-bs-target="#editModal">➕ 添加认证用户</button>
        </div>

        <div class="card">
            <div class="table-responsive">
                <table class="table table-hover align-middle mb-0">
                    <thead class="table-light"><tr><th>ID</th><th>排序</th><th>预览信息</th><th>状态</th><th>操作</th></tr></thead>
                    <tbody>
                    {% for u in users %}
                    <tr>
                        <td>{{ u.tg_id }}</td>
                        <td>{{ u.id }}</td>
                        <td>
                            {% set data = u.profile_data | from_json %}
                            {% for k, v in data.items() %}
                                {% if v and k != 'image' and loop.index < 4 %}
                                <span class="badge bg-light text-dark border">{{ v }}</span>
                                {% endif %}
                            {% endfor %}
                        </td>
                        <td>
                            {% if u.online %}<span class="text-success">● 在线</span>
                            {% else %}<span class="text-muted">○ 离线</span>{% endif %}
                        </td>
                        <td>
                            <a href="/delete/{{ u.id }}" class="btn btn-sm btn-outline-danger" onclick="return confirm('删除？')">删除</a>
                            <button class="btn btn-sm btn-outline-primary" onclick='editUser({{ u.id }}, {{ u.tg_id }}, {{ u.profile_data | tojson }})'>编辑</button>
                        </td>
                    </tr>
                    {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>

        <!-- 编辑/添加 模态框 -->
        <div class="modal fade" id="editModal" tabindex="-1">
            <div class="modal-dialog modal-lg">
                <form method="post" action="/update_user" class="modal-content">
                    <div class="modal-header"><h5 class="modal-title">编辑用户资料</h5><button type="button" class="btn-close" data-bs-dismiss="modal"></button></div>
                    <div class="modal-body">
                        <input type="hidden" name="db_id" id="db_id">
                        <div class="mb-3"><label>Telegram ID (必填)</label><input type="number" name="tg_id" id="tg_id" class="form-control" required></div>
                        <div class="row mb-3">
                            <div class="col"><label>加天数</label><input type="number" name="days" class="form-control" value="0"></div>
                            <div class="col"><label>加积分</label><input type="number" name="points" class="form-control" value="0"></div>
                        </div>
                        <hr>
                        
                        <!-- 动态渲染表单 (还原截图3) -->
                        {% for f in fields %}
                        <div class="mb-3 row">
                            <label class="col-sm-2 col-form-label">{{ f.label }}</label>
                            <div class="col-sm-10">
                                {% if f.type == 'select' %}
                                <select name="field_{{ f.key }}" id="field_{{ f.key }}" class="form-select">
                                    {% for opt in f.options.split(',') %}
                                    <option value="{{ opt }}">{{ opt }}</option>
                                    {% endfor %}
                                </select>
                                {% elif f.type == 'checkbox' %}
                                <div>
                                    {% for opt in f.options.split(',') %}
                                    <div class="form-check form-check-inline">
                                        <input class="form-check-input" type="checkbox" name="field_{{ f.key }}" value="{{ opt }}">
                                        <label class="form-check-label">{{ opt }}</label>
                                    </div>
                                    {% endfor %}
                                </div>
                                {% else %}
                                <input type="text" name="field_{{ f.key }}" id="field_{{ f.key }}" class="form-control">
                                {% endif %}
                            </div>
                        </div>
                        {% endfor %}
                    </div>
                    <div class="modal-footer"><button class="btn btn-primary">保存修改</button></div>
                </form>
            </div>
        </div>
        
        <script>
            function editUser(id, tgId, profile) {
                document.getElementById('db_id').value = id;
                document.getElementById('tg_id').value = tgId;
                for (var key in profile) {
                    var el = document.getElementById('field_' + key);
                    if (el) el.value = profile[key];
                    // checkbox 简单处理略
                }
                new bootstrap.Modal(document.getElementById('editModal')).show();
            }
        </script>
        {% endif %}
    </div>
    {% endif %}
</body>
</html>
"""

# --- Flask 路由 ---
@app.template_filter('from_json')
def from_json(value): return json.loads(value)

@app.route('/')
def index():
    if not session.get('logged_in'): return render_template_string(HTML_TEMPLATE)
    tab = request.args.get('tab', 'users')
    
    return render_template_string(HTML_TEMPLATE, 
        tab=tab, session=session,
        users=User.query.all(),
        fields=get_conf('fields', DEFAULT_FIELDS),
        fields_json=json.dumps(get_conf('fields', DEFAULT_FIELDS), indent=4, ensure_ascii=False),
        template_str=get_conf('template', DEFAULT_TEMPLATE),
        sys=get_conf('system', DEFAULT_SYSTEM)
    )

@app.route('/magic_login')
def magic_login():
    token = request.args.get('token')
    if token and jwt.decode(token, SECRET_KEY, algorithms=['HS256']).get('uid') == ADMIN_ID:
        session['logged_in'] = True
        return redirect('/')
    return "Error", 403

@app.route('/save_system', methods=['POST'])
def save_system():
    if not session.get('logged_in'): return redirect('/')
    sys_conf = {
        "checkin_open": request.form.get('checkin_open') == 'on',
        "checkin_cmd": request.form.get('checkin_cmd', '/daka'),
        "query_open": request.form.get('query_open') == 'on',
        "query_cmd": request.form.get('query_cmd', '/online'),
        "online_emoji": request.form.get('online_emoji', '🟢'),
        "offline_emoji": request.form.get('offline_emoji', '🔴'),
        "page_size": request.form.get('page_size', 10)
    }
    set_conf('system', sys_conf)
    return redirect('/?tab=system')

@app.route('/save_fields', methods=['POST'])
def save_fields():
    if not session.get('logged_in'): return redirect('/')
    try: set_conf('fields', json.loads(request.form.get('fields_json')))
    except: pass
    return redirect('/?tab=fields')

@app.route('/save_template', methods=['POST'])
def save_template():
    if not session.get('logged_in'): return redirect('/')
    set_conf('template', request.form.get('template'))
    return redirect('/?tab=template')

@app.route('/update_user', methods=['POST'])
def update_user():
    if not session.get('logged_in'): return redirect('/')
    tg_id = int(request.form.get('tg_id'))
    user = User.query.filter_by(tg_id=tg_id).first()
    if not user:
        user = User(tg_id=tg_id)
        db.session.add(user)

    fields = get_conf('fields', DEFAULT_FIELDS)
    data = {}
    for f in fields:
        key = f['key']
        if f['type'] == 'checkbox':
            vals = request.form.getlist(f"field_{key}")
            data[key] = ",".join(vals)
        else:
            data[key] = request.form.get(f"field_{key}", "")
            
    user.profile_data = json.dumps(data, ensure_ascii=False)
    
    days = int(request.form.get('days', 0))
    if days > 0:
        now = datetime.now()
        base = user.expiration_date if (user.expiration_date and user.expiration_date > now) else now
        user.expiration_date = base + timedelta(days=days)
    
    user.points += int(request.form.get('points', 0))
    db.session.commit()
    return redirect('/')

@app.route('/delete/<int:id>')
def delete_user(id):
    if session.get('logged_in'):
        User.query.filter_by(id=id).delete()
        db.session.commit()
    return redirect('/')

# --- 核心动态 Bot 逻辑 ---
async def dynamic_command_handler(update: Update, context):
    """
    一个处理器搞定所有指令！
    它会去读取数据库配置，看看用户发的指令是不是我们设置的 '/daka' 或 '/online'
    """
    msg = update.message.text.strip().split()[0] # 获取指令部分，如 /daka
    sys = get_conf('system', DEFAULT_SYSTEM)
    user = update.effective_user

    # 1. 处理打卡
    if msg == sys['checkin_cmd']:
        if not sys['checkin_open']: return await update.message.reply_text("⛔️ 打卡功能已关闭")
        
        with app.app_context():
            u = User.query.filter_by(tg_id=user.id).first()
            if not u: return await update.message.reply_text("请联系管理员认证")
            
            u.checkin_time = datetime.now()
            u.online = True
            db.session.commit()
            
            # 这里简单回复，实际可扩展配置打卡回复模板
            await update.message.reply_text(f"✅ {user.first_name} 打卡成功！状态已设为在线。")
            return

    # 2. 处理查询
    if msg == sys['query_cmd']:
        if not sys['query_open']: return await update.message.reply_text("⛔️ 查询功能已关闭")
        
        with app.app_context():
            tpl = get_conf('template', DEFAULT_TEMPLATE)
            fields_def = get_conf('fields', DEFAULT_FIELDS)
            label_map = {f['key']: f['label'] for f in fields_def}
            
            # 获取在线用户 (简单逻辑：24小时内打过卡)
            since = datetime.now() - timedelta(days=1)
            users = User.query.filter(User.checkin_time >= since).all()
            
            if not users: return await update.message.reply_text("😢 暂无在线用户")
            
            reply_msg = ""
            for u in users:
                try:
                    data = json.loads(u.profile_data)
                    line = tpl
                    
                    # 替换 {onlineEmoji}
                    line = line.replace("{onlineEmoji}", sys['online_emoji'] if u.online else sys['offline_emoji'])
                    
                    # 替换 {老师名字} 等动态字段
                    for key, val in data.items():
                        if key in label_map:
                            line = line.replace(f"{{{label_map[key]}}}", str(val))
                    
                    # 清理没填的标签
                    line = re.sub(r'\{.*?\}', '无', line)
                    reply_msg += line + "\n----------------\n"
                except: continue
            
            await update.message.reply_text(reply_msg, parse_mode='HTML')
            return

# 管理员入口
async def admin_start(update: Update, context):
    if update.effective_user.id == ADMIN_ID:
        token = jwt.encode({'uid': ADMIN_ID, 'exp': time.time()+3600}, SECRET_KEY)
        url = f"{RAILWAY_URL}/magic_login?token={token}"
        await update.message.reply_text("👋 管理员入口：", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🚀 打开高级后台", url=url)]]))

# --- 启动 ---
def run_flask(): app.run(host='0.0.0.0', port=PORT, use_reloader=False)

async def run_bot():
    if not TOKEN: return
    app_bot = Application.builder().token(TOKEN).build()
    
    # 注册管理员指令
    app_bot.add_handler(CommandHandler("start", admin_start))
    
    # 【核心】使用通用的 MessageHandler 来接管所有指令
    # 这样你才能在后台改指令，而不用改代码！
    app_bot.add_handler(MessageHandler(filters.COMMAND, dynamic_command_handler))
    
    await app_bot.initialize()
    await app_bot.start()
    await app_bot.updater.start_polling()
    await asyncio.Event().wait()

if __name__ == '__main__':
    with app.app_context():
        # db.drop_all() # 需要重置表结构时取消注释一次
        db.create_all()
    threading.Thread(target=run_flask, daemon=True).start()
    try: asyncio.run(run_bot())
    except KeyboardInterrupt: pass
