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
from telegram.ext import Application, CommandHandler, MessageHandler, filters

# --- 1. 基础配置 ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

DB_URI = os.getenv('DATABASE_URL', 'sqlite:///bot.db')
if DB_URI.startswith("postgres://"):
    DB_URI = DB_URI.replace("postgres://", "postgresql://", 1)

TOKEN = os.getenv('TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_ID', 0))
SECRET_KEY = os.getenv('SECRET_KEY', 'secret_key_123')
PORT = int(os.getenv('PORT', 5000))
RAILWAY_URL = os.getenv('RAILWAY_PUBLIC_DOMAIN', '')
if RAILWAY_URL and not RAILWAY_URL.startswith('http'): RAILWAY_URL = f"https://{RAILWAY_URL}"

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = DB_URI
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = SECRET_KEY
db = SQLAlchemy(app)

# --- 2. 数据库模型 ---
class Config(db.Model):
    key = db.Column(db.String(50), primary_key=True)
    value = db.Column(db.Text)

class User(db.Model):
    __tablename__ = 'users_v8' # 升级表名以重置结构
    id = db.Column(db.Integer, primary_key=True)
    tg_id = db.Column(db.BigInteger, unique=True, index=True)
    username = db.Column(db.String(100))
    # 核心数据存 JSON: {"name": "西西", "region": "南山", "price": "1000", ...}
    profile_data = db.Column(db.Text, default='{}') 
    expiration_date = db.Column(db.DateTime)
    points = db.Column(db.Integer, default=0)
    checkin_time = db.Column(db.DateTime)
    online = db.Column(db.Boolean, default=False)
    
    @property
    def is_expired(self):
        return self.expiration_date and datetime.now() > self.expiration_date

# --- 默认配置 (完全复刻截图9) ---
DEFAULT_FIELDS = [
    {"key": "name", "label": "老师名字", "type": "text", "search": True},
    {"key": "contact", "label": "联系方式", "type": "text", "search": True},
    {"key": "link", "label": "频道链接", "type": "text", "search": True},
    {"key": "region", "label": "地区", "type": "select", "options": ["福田","南山","罗湖","龙华","龙岗","宝安","光明","外出"], "search": True},
    {"key": "price", "label": "价位", "type": "text", "search": True},
    {"key": "cup", "label": "胸围", "type": "select", "options": ["胸A","胸B","胸C","胸D","胸E","胸F","胸G"], "search": True},
    {"key": "height", "label": "身高", "type": "text", "search": True},
    {"key": "desc", "label": "双向联系", "type": "text", "search": False}
]

DEFAULT_TEMPLATE = "<b>{onlineEmoji} {老师名字}</b>\n👙 胸围：{胸围}\n💰 价位：{价位}\n📍 地区：{地区}\n🔗 链接：<a href='{频道链接}'>点击查看详情</a>"
DEFAULT_SYSTEM = {"checkin_open": True, "query_open": True, "online_emoji": "🟢", "offline_emoji": "🔴"}

# --- 辅助函数 ---
def get_conf(key, default):
    c = Config.query.get(key)
    return json.loads(c.value) if c else default

def set_conf(key, value):
    c = Config.query.get(key)
    if not c: db.session.add(Config(key=key, value=json.dumps(value)))
    else: c.value = json.dumps(value)
    db.session.commit()

# --- 后台 HTML (单文件包含 CSS/JS) ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>阿福Bot 管理系统</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <style>
        :root { --primary-color: #5c6bc0; --bg-color: #f3f4f6; }
        body { background-color: var(--bg-color); font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; }
        
        /* 侧边栏 */
        .sidebar { background: #fff; width: 250px; position: fixed; height: 100vh; border-right: 1px solid #e5e7eb; z-index: 1000; }
        .brand { padding: 20px; font-size: 20px; font-weight: bold; color: var(--primary-color); display: flex; align-items: center; gap: 10px; }
        .nav-item { padding: 12px 24px; color: #4b5563; display: flex; align-items: center; gap: 12px; text-decoration: none; transition: 0.2s; }
        .nav-item:hover, .nav-item.active { background: #eef2ff; color: var(--primary-color); border-right: 3px solid var(--primary-color); }
        
        /* 主内容 */
        .main-content { margin-left: 250px; padding: 30px; }
        .card { border: none; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); background: #fff; margin-bottom: 24px; }
        .card-header { background: #fff; border-bottom: 1px solid #f3f4f6; padding: 20px; font-weight: 600; display: flex; justify-content: space-between; align-items: center; }
        
        /* 截图8复刻：表格样式 */
        .table thead th { border-bottom: 2px solid #e5e7eb; color: #9ca3af; font-weight: 500; text-transform: uppercase; font-size: 12px; padding: 15px; }
        .table td { padding: 15px; vertical-align: middle; color: #374151; }
        .btn-custom { background: var(--primary-color); color: white; border: none; padding: 8px 16px; border-radius: 6px; font-size: 14px; }
        .btn-custom:hover { background: #4f5b9e; color: white; }
        .search-box { border: 1px solid #e5e7eb; padding: 8px 12px; border-radius: 6px; width: 250px; }
        
        /* 截图1复刻：自定义富文本编辑器 */
        .editor-toolbar { border: 1px solid #e5e7eb; border-bottom: none; border-radius: 6px 6px 0 0; padding: 8px; background: #f9fafb; display: flex; gap: 5px; }
        .editor-btn { background: none; border: none; padding: 4px 8px; border-radius: 4px; color: #6b7280; cursor: pointer; }
        .editor-btn:hover { background: #e5e7eb; color: #000; }
        .editor-content { border: 1px solid #e5e7eb; border-radius: 0 0 6px 6px; min-height: 200px; padding: 15px; outline: none; }
        .editor-content:focus { border-color: var(--primary-color); box-shadow: 0 0 0 2px rgba(92,107,192,0.2); }
        .var-tag { display: inline-block; padding: 2px 8px; background: #e0e7ff; color: var(--primary-color); border-radius: 4px; font-size: 12px; margin-right: 5px; cursor: pointer; user-select: none; }
        
        /* 截图9复刻：标签输入框 */
        .tag-container { display: flex; flex-wrap: wrap; gap: 5px; border: 1px solid #ced4da; padding: 5px; border-radius: 0.25rem; min-height: 38px; }
        .tag-badge { background: #d1fae5; color: #065f46; padding: 2px 8px; border-radius: 4px; font-size: 12px; display: flex; align-items: center; gap: 5px; }
        .tag-remove { cursor: pointer; font-weight: bold; }
        .tag-input { border: none; outline: none; flex-grow: 1; min-width: 60px; font-size: 14px; }
    </style>
</head>
<body>
    {% if not session.get('logged_in') %}
    <div style="height:100vh; display:flex; justify-content:center; align-items:center;">
        <div class="card p-5 text-center" style="width: 400px;">
            <h4 class="mb-3">🔐 系统登录</h4>
            <p class="text-muted">请在 Telegram 发送 /start 获取链接</p>
        </div>
    </div>
    {% else %}
    
    <div class="sidebar">
        <div class="brand"><i class="fas fa-robot"></i> 阿福Bot Pro</div>
        <div class="mt-3">
            <small class="px-4 text-muted text-uppercase" style="font-size:11px">Management</small>
            <a href="/?tab=users" class="nav-item {{ 'active' if tab=='users' else '' }}"><i class="fas fa-users"></i> 认证用户列表</a>
            <a href="/?tab=fields" class="nav-item {{ 'active' if tab=='fields' else '' }}"><i class="fas fa-sliders-h"></i> 字段配置 (截图9)</a>
            <a href="/?tab=template" class="nav-item {{ 'active' if tab=='template' else '' }}"><i class="fas fa-file-alt"></i> 消息模板 (截图1)</a>
            <a href="/?tab=system" class="nav-item {{ 'active' if tab=='system' else '' }}"><i class="fas fa-cog"></i> 系统设置</a>
            <a href="/logout" class="nav-item text-danger mt-5"><i class="fas fa-sign-out-alt"></i> 退出登录</a>
        </div>
    </div>

    <div class="main-content">
        <!-- 1. 认证用户列表 (完全复刻截图 8) -->
        {% if tab == 'users' %}
        <div class="card">
            <div class="card-header">
                <div class="d-flex gap-2">
                    <button class="btn btn-custom" onclick="openAddModal()">添加认证用户</button>
                    <button class="btn btn-outline-primary" onclick="location.href='/?tab=template'">修改模板</button>
                </div>
                <div class="d-flex align-items-center gap-2">
                    <span>Show</span>
                    <select class="form-select form-select-sm" style="width:70px" onchange="window.location.href='/?tab=users&limit='+this.value">
                        <option value="10" {{ 'selected' if limit==10 }}>10</option>
                        <option value="50" {{ 'selected' if limit==50 }}>50</option>
                        <option value="100" {{ 'selected' if limit==100 }}>100</option>
                    </select>
                    <span>entries</span>
                </div>
            </div>
            <div class="p-3">
                <input type="text" id="userSearch" class="search-box float-end mb-3" placeholder="搜索用户..." onkeyup="filterTable()">
                <table class="table table-hover" id="userTable">
                    <thead>
                        <tr>
                            <th>TG ID</th>
                            <th>预览信息</th>
                            <th>过期时间</th>
                            <th class="text-end">操作</th>
                        </tr>
                    </thead>
                    <tbody>
                    {% for u in users %}
                    <tr>
                        <td>{{ u.tg_id }}</td>
                        <td>
                            {% set d = u.profile_data | from_json %}
                            <div class="d-flex flex-wrap gap-1">
                                {% for k, v in d.items() %}
                                    {% if v and loop.index <= 4 %}
                                    <span class="badge bg-light text-dark border">{{ v }}</span>
                                    {% endif %}
                                {% endfor %}
                            </div>
                        </td>
                        <td>{{ u.expiration_date.strftime('%Y-%m-%d') if u.expiration_date else '永久' }}</td>
                        <td class="text-end">
                            <button class="btn btn-sm btn-primary" onclick='editUser({{ u.id }}, {{ u.tg_id }}, {{ u.profile_data | tojson }})'>编辑</button>
                            <a href="/del_user/{{ u.id }}" class="btn btn-sm btn-secondary" onclick="return confirm('确认删除？')">删除</a>
                        </td>
                    </tr>
                    {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>

        <!-- 2. 字段配置 (完全复刻截图 9) -->
        {% elif tab == 'fields' %}
        <div class="card">
            <div class="card-header">字段配置</div>
            <div class="card-body">
                <p class="text-muted mb-4">删除字段需谨慎，删除字段数据也会删除。</p>
                <form action="/save_fields" method="post">
                    <input type="hidden" name="fields_json" id="fields_json_input">
                    <div id="fields_container"></div>
                    <button type="button" class="btn btn-outline-primary mt-3 w-100" onclick="addFieldRow()">+ 添加新字段</button>
                    <button type="submit" class="btn btn-custom mt-3 w-100" onclick="serializeFields()">保存所有配置</button>
                </form>
            </div>
        </div>
        <script>
            // 前端动态渲染字段行，复刻截图9的复杂交互
            let fieldsData = {{ fields_json | safe }};
            
            function renderFields() {
                const container = document.getElementById('fields_container');
                container.innerHTML = '';
                fieldsData.forEach((f, index) => {
                    let optionsHtml = '';
                    if (f.type === 'select' || f.type === 'checkbox') {
                        // 标签式选项编辑
                        let tags = (f.options || []).map(o => `<span class="tag-badge">${o}<span class="tag-remove" onclick="removeOption(${index}, '${o}')">&times;</span></span>`).join('');
                        optionsHtml = `
                            <div class="tag-container mt-2" onclick="document.getElementById('opt_in_${index}').focus()">
                                ${tags}
                                <input type="text" class="tag-input" id="opt_in_${index}" placeholder="输入选项回车添加" onkeydown="addOption(event, ${index})">
                            </div>`;
                    }

                    const html = `
                    <div class="row align-items-center mb-3 g-2 border-bottom pb-3">
                        <div class="col-md-3">
                            <input type="text" class="form-control" value="${f.label}" onchange="fieldsData[${index}].label=this.value" placeholder="字段名称">
                        </div>
                        <div class="col-md-2">
                            <select class="form-select" onchange="updateType(${index}, this.value)">
                                <option value="text" ${f.type=='text'?'selected':''}>文本</option>
                                <option value="select" ${f.type=='select'?'selected':''}>单选</option>
                                <option value="checkbox" ${f.type=='checkbox'?'selected':''}>多选</option>
                            </select>
                        </div>
                        <div class="col-md-1 text-center">
                            <div class="form-check form-switch d-inline-block">
                                <input class="form-check-input" type="checkbox" ${f.search?'checked':''} onchange="fieldsData[${index}].search=this.checked">
                            </div>
                        </div>
                        <div class="col-md-5">
                            ${optionsHtml}
                        </div>
                        <div class="col-md-1 text-end">
                            <button type="button" class="btn btn-sm btn-danger" onclick="removeField(${index})">&times;</button>
                        </div>
                    </div>`;
                    container.innerHTML += html;
                });
            }

            function updateType(idx, type) {
                fieldsData[idx].type = type;
                if (!fieldsData[idx].options) fieldsData[idx].options = [];
                renderFields();
            }
            function addOption(e, idx) {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    const val = e.target.value.trim();
                    if (val) {
                        if (!fieldsData[idx].options) fieldsData[idx].options = [];
                        fieldsData[idx].options.push(val);
                        renderFields();
                        // 重新聚焦
                        setTimeout(() => document.getElementById(`opt_in_${idx}`).focus(), 50); 
                    }
                }
            }
            function removeOption(idx, val) {
                fieldsData[idx].options = fieldsData[idx].options.filter(o => o !== val);
                renderFields();
            }
            function addFieldRow() {
                fieldsData.push({key: 'new_'+Date.now(), label: '', type: 'text', search: false});
                renderFields();
            }
            function removeField(idx) {
                fieldsData.splice(idx, 1);
                renderFields();
            }
            function serializeFields() {
                document.getElementById('fields_json_input').value = JSON.stringify(fieldsData);
            }
            // Init
            window.addEventListener('DOMContentLoaded', renderFields);
        </script>

        <!-- 3. 消息模板 (完全复刻截图 1) -->
        {% elif tab == 'template' %}
        <div class="card">
            <div class="card-header">查询消息用户模板</div>
            <div class="card-body">
                <div class="mb-3">
                    <label class="form-label text-muted">可用变量 (点击插入):</label>
                    <div id="varTags">
                        <span class="var-tag" onclick="execCmd('insertText', '{onlineEmoji}')">{在线表情}</span>
                        {% for f in fields %}
                        <span class="var-tag" onclick="execCmd('insertText', '{'+'{{ f.label }}'+'}')">{ {{ f.label }} }</span>
                        {% endfor %}
                    </div>
                </div>

                <!-- 自定义编辑器 -->
                <div class="editor-toolbar">
                    <button class="editor-btn" onclick="execCmd('bold')" title="加粗"><b>B</b></button>
                    <button class="editor-btn" onclick="execCmd('italic')" title="斜体"><i>I</i></button>
                    <button class="editor-btn" onclick="execCmd('underline')" title="下划线"><u>U</u></button>
                    <button class="editor-btn" onclick="execCmd('strikethrough')" title="删除线"><s>S</s></button>
                    <button class="editor-btn" onclick="promptLink()" title="插入链接"><i class="fas fa-link"></i></button>
                </div>
                <div id="richEditor" class="editor-content" contenteditable="true">{{ template_str | safe }}</div>
                
                <form method="post" action="/save_template" onsubmit="syncContent()">
                    <input type="hidden" name="template" id="templateInput">
                    <button class="btn btn-custom mt-3">保存模板</button>
                </form>
            </div>
        </div>
        <script>
            function execCmd(cmd, val=null) {
                document.execCommand(cmd, false, val);
                document.getElementById('richEditor').focus();
            }
            function promptLink() {
                const url = prompt("输入链接地址:", "https://");
                if (url) execCmd('createLink', url);
            }
            function syncContent() {
                // 将 contenteditable 的 HTML 内容转为 input value
                document.getElementById('templateInput').value = document.getElementById('richEditor').innerHTML;
            }
        </script>
        
        <!-- 4. 系统设置 -->
        {% elif tab == 'system' %}
        <div class="card">
            <div class="card-header">系统设置</div>
            <div class="card-body">
                <form action="/save_system" method="post">
                    <div class="mb-3 form-check form-switch">
                        <input class="form-check-input" type="checkbox" name="checkin_open" {{ 'checked' if sys.checkin_open }}>
                        <label>开启打卡功能</label>
                    </div>
                    <div class="mb-3 form-check form-switch">
                        <input class="form-check-input" type="checkbox" name="query_open" {{ 'checked' if sys.query_open }}>
                        <label>开启查询功能</label>
                    </div>
                    <div class="row">
                        <div class="col"><label>在线Emoji</label><input name="online_emoji" class="form-control" value="{{ sys.online_emoji }}"></div>
                        <div class="col"><label>离线Emoji</label><input name="offline_emoji" class="form-control" value="{{ sys.offline_emoji }}"></div>
                    </div>
                    <button class="btn btn-custom mt-3">保存</button>
                </form>
            </div>
        </div>
        {% endif %}
    </div>

    <!-- 用户添加/编辑 模态框 (Bootstrap 5) -->
    <div class="modal fade" id="userModal" tabindex="-1">
        <div class="modal-dialog modal-lg">
            <form method="post" action="/update_user" class="modal-content">
                <div class="modal-header">
                    <h5 class="modal-title">认证用户资料</h5>
                    <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                </div>
                <div class="modal-body">
                    <input type="hidden" name="db_id" id="modal_db_id">
                    <div class="mb-3">
                        <label>Telegram ID <span class="text-danger">*</span></label>
                        <input type="number" name="tg_id" id="modal_tg_id" class="form-control" required>
                    </div>
                    
                    <!-- 动态字段渲染区域 -->
                    <div id="modal_fields_area">
                    {% for f in fields %}
                        <div class="mb-3">
                            <label class="form-label">{{ f.label }}</label>
                            {% if f.type == 'select' %}
                                <select name="field_{{ f.key }}" id="field_{{ f.key }}" class="form-select">
                                    <option value="">请选择...</option>
                                    {% for o in f.options %}
                                    <option value="{{ o }}">{{ o }}</option>
                                    {% endfor %}
                                </select>
                            {% elif f.type == 'checkbox' %}
                                <div>
                                {% for o in f.options %}
                                    <div class="form-check form-check-inline">
                                        <input class="form-check-input" type="checkbox" name="field_{{ f.key }}" value="{{ o }}">
                                        <label class="form-check-label">{{ o }}</label>
                                    </div>
                                {% endfor %}
                                </div>
                            {% else %}
                                <input type="text" name="field_{{ f.key }}" id="field_{{ f.key }}" class="form-control">
                            {% endif %}
                        </div>
                    {% endfor %}
                    </div>

                    <hr>
                    <div class="row">
                        <div class="col"><label>加天数</label><input type="number" name="days" class="form-control" value="0"></div>
                        <div class="col"><label>加积分</label><input type="number" name="points" class="form-control" value="0"></div>
                    </div>
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">取消</button>
                    <button type="submit" class="btn btn-custom">保存</button>
                </div>
            </form>
        </div>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js"></script>
    <script>
        // 用户搜索功能
        function filterTable() {
            var input = document.getElementById("userSearch");
            var filter = input.value.toUpperCase();
            var table = document.getElementById("userTable");
            var tr = table.getElementsByTagName("tr");
            for (var i = 1; i < tr.length; i++) {
                var td = tr[i].getElementsByTagName("td")[1]; // 搜索第二列(预览信息)
                if (td) {
                    var txtValue = td.textContent || td.innerText;
                    if (txtValue.toUpperCase().indexOf(filter) > -1) {
                        tr[i].style.display = "";
                    } else {
                        tr[i].style.display = "none";
                    }
                }       
            }
        }

        // 打开添加模态框
        var userModal;
        window.onload = function() {
            userModal = new bootstrap.Modal(document.getElementById('userModal'));
        };
        
        function openAddModal() {
            document.getElementById('modal_db_id').value = '';
            document.getElementById('modal_tg_id').value = '';
            document.querySelectorAll('#modal_fields_area input[type=text]').forEach(e => e.value = '');
            userModal.show();
        }

        function editUser(id, tgId, profile) {
            document.getElementById('modal_db_id').value = id;
            document.getElementById('modal_tg_id').value = tgId;
            
            // 填充动态字段
            for (var key in profile) {
                var el = document.getElementById('field_' + key);
                if (el) {
                    if (el.type === 'checkbox') {
                         // Checkbox处理略繁琐，这里简化：如果包含了值就勾选
                    } else {
                        el.value = profile[key];
                    }
                }
            }
            userModal.show();
        }
    </script>
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
    limit = int(request.args.get('limit', 10))
    
    users = []
    if tab == 'users':
        users = User.query.order_by(User.id.desc()).limit(limit).all()
        
    return render_template_string(HTML_TEMPLATE, 
        tab=tab, limit=limit, session=session, users=users,
        fields=get_conf('fields', DEFAULT_FIELDS),
        fields_json=json.dumps(get_conf('fields', DEFAULT_FIELDS)),
        template_str=get_conf('template', DEFAULT_TEMPLATE),
        sys=get_conf('system', DEFAULT_SYSTEM)
    )

@app.route('/magic_login')
def magic_login():
    token = request.args.get('token')
    if token and jwt.decode(token, SECRET_KEY, algorithms=['HS256']).get('uid') == ADMIN_ID:
        session['logged_in'] = True
        return redirect('/?tab=users')
    return "Error", 403

@app.route('/update_user', methods=['POST'])
def update_user():
    if not session.get('logged_in'): return redirect('/')
    tg_id = int(request.form.get('tg_id'))
    
    user = User.query.filter_by(tg_id=tg_id).first()
    if not user:
        user = User(tg_id=tg_id)
        db.session.add(user)
    
    # 动态字段存储
    fields = get_conf('fields', DEFAULT_FIELDS)
    data = {}
    for f in fields:
        k = f['key']
        if f['type'] == 'checkbox':
            data[k] = ",".join(request.form.getlist(f"field_{k}"))
        else:
            data[k] = request.form.get(f"field_{k}", "")
    user.profile_data = json.dumps(data, ensure_ascii=False)
    
    # 日期积分处理
    days = int(request.form.get('days', 0))
    if days:
        now = datetime.now()
        base = user.expiration_date if (user.expiration_date and user.expiration_date > now) else now
        user.expiration_date = base + timedelta(days=days)
    user.points += int(request.form.get('points', 0))
    
    db.session.commit()
    return redirect('/?tab=users')

@app.route('/del_user/<int:id>')
def del_user(id):
    if session.get('logged_in'):
        User.query.filter_by(id=id).delete()
        db.session.commit()
    return redirect('/?tab=users')

@app.route('/save_fields', methods=['POST'])
def save_fields():
    if session.get('logged_in'):
        set_conf('fields', json.loads(request.form.get('fields_json')))
    return redirect('/?tab=fields')

@app.route('/save_template', methods=['POST'])
def save_template():
    if session.get('logged_in'):
        set_conf('template', request.form.get('template'))
    return redirect('/?tab=template')

@app.route('/save_system', methods=['POST'])
def save_system():
    if session.get('logged_in'):
        sys = {
            "checkin_open": request.form.get('checkin_open') == 'on',
            "query_open": request.form.get('query_open') == 'on',
            "online_emoji": request.form.get('online_emoji'),
            "offline_emoji": request.form.get('offline_emoji')
        }
        set_conf('system', sys)
    return redirect('/?tab=system')

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')

# --- Bot 逻辑 ---
async def start(update: Update, context):
    if update.effective_user.id == ADMIN_ID:
        token = jwt.encode({'uid': ADMIN_ID, 'exp': time.time()+3600}, SECRET_KEY)
        url = f"{RAILWAY_URL}/magic_login?token={token}"
        await update.message.reply_text("💼 <b>SaaS管理系统</b>\n点击下方按钮登录：", 
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🚀 进入后台", url=url)]]),
            parse_mode='HTML'
        )
    else:
        await update.message.reply_text("👋 欢迎！发送 /online 查询在线用户。")

async def online(update: Update, context):
    sys = get_conf('system', DEFAULT_SYSTEM)
    if not sys['query_open']: return await update.message.reply_text("⛔️ 查询功能已关闭")
    
    with app.app_context():
        # 获取在线用户 (24h内打卡)
        since = datetime.now() - timedelta(days=1)
        users = User.query.filter(User.checkin_time >= since).all()
        if not users: return await update.message.reply_text("😢 暂无在线用户")
        
        tpl = get_conf('template', DEFAULT_TEMPLATE)
        fields_map = {f['label']: f['key'] for f in get_conf('fields', DEFAULT_FIELDS)}
        
        msg = ""
        for u in users:
            try:
                data = json.loads(u.profile_data)
                line = tpl
                line = line.replace("{onlineEmoji}", sys['online_emoji'] if u.online else sys['offline_emoji'])
                
                # 智能替换 {标签名} -> data[key]
                for label, key in fields_map.items():
                    val = data.get(key, '未填')
                    line = line.replace(f"{{{label}}}", str(val))
                
                msg += line + "\n━━━━━━━━━━━━━━\n"
            except: continue
            
        await update.message.reply_text(msg, parse_mode='HTML', disable_web_page_preview=True)

# --- 启动 ---
def run_flask(): app.run(host='0.0.0.0', port=PORT, use_reloader=False)

async def run_bot():
    if not TOKEN: return
    app_bot = Application.builder().token(TOKEN).build()
    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CommandHandler("online", online))
    await app_bot.initialize()
    await app_bot.start()
    await app_bot.updater.start_polling()
    await asyncio.Event().wait()

if __name__ == '__main__':
    with app.app_context():
        # db.drop_all() # ⚠️ 首次运行解开注释以重置数据库
        db.create_all()
    threading.Thread(target=run_flask, daemon=True).start()
    try: asyncio.run(run_bot())
    except KeyboardInterrupt: pass
