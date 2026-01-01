from flask import Blueprint, render_template_string, request, redirect, session, url_for
from models import db, User, AutoReply
from datetime import datetime, timedelta

web_bp = Blueprint('web', __name__)

# 把 HTML 模板还是放在代码里，避免你建 templates 文件夹出错
HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>完整版管理后台</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body class="p-4">
    <h2>📊 会员管理系统</h2>
    <hr>
    <table class="table">
        <thead><tr><th>ID</th><th>用户</th><th>等级</th><th>过期时间</th><th>积分</th><th>操作</th></tr></thead>
        <tbody>
        {% for u in users %}
        <tr>
            <td>{{ u.telegram_id }}</td>
            <td>{{ u.username }}</td>
            <td>{{ u.level }}</td>
            <td>{{ u.expiration_date }}</td>
            <td>{{ u.points }}</td>
            <td><a href="#" class="btn btn-sm btn-primary">编辑</a></td>
        </tr>
        {% endfor %}
    </tbody>
    </table>
</body>
</html>
"""

@web_bp.route('/')
def index():
    users = User.query.all()
    return render_template_string(HTML, users=users)
