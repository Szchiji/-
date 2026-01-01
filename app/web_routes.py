from flask import Blueprint, render_template, request, redirect, session, jsonify
from .models import db, User
from .utils import get_conf, set_conf
from .models import DEFAULT_FIELDS, DEFAULT_SYSTEM
from . import global_bot, global_loop
import json
import jwt
import os
import asyncio
import re
from datetime import datetime, timedelta

web_bp = Blueprint('web', __name__)

@web_bp.route('/')
def index():
    if not session.get('logged_in'): return render_template('base.html', page='login')
    return redirect('/users')

@web_bp.route('/users')
def page_users():
    if not session.get('logged_in'): return redirect('/')
    q = request.args.get('q', '')
    query = User.query
    if q: query = query.filter(User.profile_data.contains(q))
    users = query.order_by(User.id.desc()).all()
    fields = get_conf('fields', DEFAULT_FIELDS)
    return render_template('users.html', users=users, fields=fields, q=q)

@web_bp.route('/fields')
def page_fields():
    if not session.get('logged_in'): return redirect('/')
    fields = get_conf('fields', DEFAULT_FIELDS)
    return render_template('fields.html', fields=fields)

@web_bp.route('/system')
def page_system():
    if not session.get('logged_in'): return redirect('/')
    sys = get_conf('system', DEFAULT_SYSTEM)
    fields = get_conf('fields', DEFAULT_FIELDS)
    return render_template('system.html', sys=sys, fields=fields)

# --- API ---
@app.template_filter('from_json')
def from_json(value): return json.loads(value)

@web_bp.route('/api/save_user', methods=['POST'])
def api_save_user():
    if not session.get('logged_in'): return "Auth Fail", 403
    data = request.json
    tg_id = int(data.get('tg_id'))
    user = User.query.filter_by(tg_id=tg_id).first()
    if not user:
        user = User(tg_id=tg_id)
        db.session.add(user)
    
    user.profile_data = json.dumps(data.get('profile', {}), ensure_ascii=False)
    days = int(data.get('add_days', 0))
    if days:
        now = datetime.now()
        base = user.expiration_date if (user.expiration_date and user.expiration_date > now) else now
        user.expiration_date = base + timedelta(days=days)
    
    db.session.commit()
    return jsonify({"status": "ok"})

@web_bp.route('/api/delete_user', methods=['POST'])
def api_delete_user():
    if not session.get('logged_in'): return "Auth Fail", 403
    uid = request.json.get('id')
    User.query.filter_by(id=uid).delete()
    db.session.commit()
    return jsonify({"status": "ok"})

@web_bp.route('/api/save_fields', methods=['POST'])
def api_save_fields():
    if not session.get('logged_in'): return "Auth Fail", 403
    set_conf('fields', request.json)
    return jsonify({"status": "ok"})

@web_bp.route('/api/save_system', methods=['POST'])
def api_save_system():
    if not session.get('logged_in'): return "Auth Fail", 403
    set_conf('system', request.json)
    return jsonify({"status": "ok"})

# 推送功能 (截图8)
@web_bp.route('/api/push_user', methods=['POST'])
def api_push_user():
    if not session.get('logged_in'): return "Auth Fail", 403
    uid = request.json.get('id')
    user = User.query.filter_by(id=uid).first()
    
    from app import global_bot, global_loop # 延迟导入避免循环引用
    
    if not global_bot: return jsonify({"status": "error", "msg": "机器人未启动"})
    
    sys = get_conf('system', DEFAULT_SYSTEM)
    channel = sys.get('push_channel_id')
    if not channel: return jsonify({"status": "error", "msg": "未设置推送频道ID"})
    
    # 渲染消息
    tpl = sys.get('template', '')
    fields = get_conf('fields', DEFAULT_FIELDS)
    label_map = {f['key']: f['label'] for f in fields}
    
    try:
        data = json.loads(user.profile_data)
        line = tpl.replace("{onlineEmoji}", sys['online_emoji'] if user.online else sys['offline_emoji'])
        for k, v in data.items():
            if k in label_map: line = line.replace(f"{{{label_map[k]}}}", str(v))
        line = re.sub(r'\{.*?\}', '', line)
        
        asyncio.run_coroutine_threadsafe(
            global_bot.send_message(chat_id=channel, text=line, parse_mode='HTML'),
            global_loop
        )
        return jsonify({"status": "ok", "msg": "已推送"})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)})

@web_bp.route('/magic_login')
def magic_login():
    token = request.args.get('token')
    if token and jwt.decode(token, os.getenv('SECRET_KEY'), algorithms=['HS256']).get('uid') == int(os.getenv('ADMIN_ID')):
        session['logged_in'] = True
        return redirect('/users')
    return "Link Invalid", 403

@web_bp.route('/logout')
def logout():
    session.clear()
    return redirect('/')
