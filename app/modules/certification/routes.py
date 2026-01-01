from flask import render_template, request, redirect, session, jsonify
from app.models import db, User, DEFAULT_FIELDS, DEFAULT_SYSTEM
from app.utils import get_conf, set_conf
from app import global_bot, global_loop
from . import cert_bp # 使用蓝图
import json
import jwt
import os
import re
import asyncio
from datetime import datetime, timedelta

# 首页重定向
@cert_bp.route('/')
def index():
    if not session.get('logged_in'): return render_template('base.html', page='login')
    return redirect('/users')

# 用户列表
@cert_bp.route('/users')
def page_users():
    if not session.get('logged_in'): return redirect('/')
    q = request.args.get('q', '')
    query = User.query
    if q: query = query.filter(User.profile_data.contains(q))
    users = query.order_by(User.id.desc()).all()
    fields = get_conf('fields', DEFAULT_FIELDS)
    return render_template('users.html', page='users', users=users, fields=fields, q=q)

# 系统设置
@cert_bp.route('/system')
def page_system():
    if not session.get('logged_in'): return redirect('/')
    sys = get_conf('system', DEFAULT_SYSTEM)
    fields = get_conf('fields', DEFAULT_FIELDS)
    return render_template('system.html', page='system', sys=sys, fields=fields)

# 字段配置
@cert_bp.route('/fields')
def page_fields():
    if not session.get('logged_in'): return redirect('/')
    fields = get_conf('fields', DEFAULT_FIELDS)
    return render_template('fields.html', page='fields', fields=fields, fields_json=json.dumps(fields))

# --- API (保持不变) ---
@cert_bp.route('/api/save_user', methods=['POST'])
def api_save_user():
    if not session.get('logged_in'): return "403", 403
    data = request.json
    try:
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
    except Exception as e: return jsonify({"status": "err", "msg": str(e)})

@cert_bp.route('/api/delete_user', methods=['POST'])
def api_delete_user():
    if not session.get('logged_in'): return "403", 403
    User.query.filter_by(id=request.json.get('id')).delete()
    db.session.commit()
    return jsonify({"status": "ok"})

@cert_bp.route('/api/save_system', methods=['POST'])
def api_save_system():
    if not session.get('logged_in'): return "403", 403
    curr = get_conf('system', DEFAULT_SYSTEM)
    curr.update(request.json)
    set_conf('system', curr)
    return jsonify({"status": "ok"})

@cert_bp.route('/api/save_fields', methods=['POST'])
def api_save_fields():
    if not session.get('logged_in'): return "403", 403
    set_conf('fields', request.json)
    return jsonify({"status": "ok"})

@cert_bp.route('/api/push_user', methods=['POST'])
def api_push_user():
    if not session.get('logged_in'): return "403", 403
    from app import global_bot, global_loop
    uid = request.json.get('id')
    user = User.query.filter_by(id=uid).first()
    sys = get_conf('system', DEFAULT_SYSTEM)
    channel = sys.get('push_channel_id')
    if not channel: return jsonify({"status": "err", "msg": "未配置推送频道ID"})
    
    tpl = sys.get('template', '')
    fields_map = {f['key']: f['label'] for f in get_conf('fields', DEFAULT_FIELDS)}
    try:
        data = json.loads(user.profile_data)
        line = tpl.replace("{onlineEmoji}", sys.get('online_emoji','🟢') if user.online else sys.get('offline_emoji','🔴'))
        for k, v in data.items():
            if k in fields_map: line = line.replace(f"{{{fields_map[k]}}}", str(v))
        line = re.sub(r'\{.*?\}', '', line)
        if global_bot and global_loop:
            asyncio.run_coroutine_threadsafe(global_bot.send_message(chat_id=channel, text=line, parse_mode='HTML'), global_loop)
            return jsonify({"status": "ok", "msg": "✅ 推送成功"})
    except Exception as e: return jsonify({"status": "err", "msg": str(e)})
    return jsonify({"status": "err", "msg": "Bot未连接"})

@cert_bp.route('/magic_login')
def magic_login():
    token = request.args.get('token')
    if token and jwt.decode(token, os.getenv('SECRET_KEY'), algorithms=['HS256']).get('uid') == int(os.getenv('ADMIN_ID')):
        session['logged_in'] = True
        return redirect('/')
    return "Login Failed", 403

@cert_bp.route('/logout')
def logout(): session.clear(); return redirect('/')
