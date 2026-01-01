from flask import Blueprint, render_template, request, redirect, session, jsonify
from .models import db, User, DEFAULT_FIELDS, DEFAULT_SYSTEM
from .utils import get_conf, set_conf
from . import global_bot, global_loop
import json
import jwt
import os
import re
import asyncio
from datetime import datetime, timedelta

web_bp = Blueprint('web', __name__)

@web_bp.route('/')
def index():
    if not session.get('logged_in'): return render_template('admin_base.html', page='login')
    return redirect('/users')

@web_bp.route('/users')
def page_users():
    if not session.get('logged_in'): return redirect('/')
    q = request.args.get('q', '')
    query = User.query
    if q: query = query.filter(User.profile_data.contains(q))
    users = query.order_by(User.id.desc()).all()
    fields = get_conf('fields', DEFAULT_FIELDS)
    return render_template('base.html', page='users', users=users, fields=fields, q=q)

@web_bp.route('/fields')
def page_fields():
    if not session.get('logged_in'): return redirect('/')
    fields = get_conf('fields', DEFAULT_FIELDS)
    return render_template('admin_base.html', page='fields', fields=fields, fields_json=json.dumps(fields))

@web_bp.route('/template')
def page_template():
    if not session.get('logged_in'): return redirect('/')
    sys = get_conf('system', DEFAULT_SYSTEM)
    fields = get_conf('fields', DEFAULT_FIELDS)
    return render_template('admin_base.html', page='template', template_str=sys.get('template',''), fields=fields)

@web_bp.route('/system')
def page_system():
    if not session.get('logged_in'): return redirect('/')
    sys = get_conf('system', DEFAULT_SYSTEM)
    return render_template('admin_base.html', page='system', sys=sys)

# --- API ---
@web_bp.route('/api/save_user', methods=['POST'])
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

@web_bp.route('/api/delete_user', methods=['POST'])
def api_delete_user():
    if not session.get('logged_in'): return "403", 403
    User.query.filter_by(id=request.json.get('id')).delete()
    db.session.commit()
    return jsonify({"status": "ok"})

@web_bp.route('/api/save_fields', methods=['POST'])
def api_save_fields():
    if not session.get('logged_in'): return "403", 403
    set_conf('fields', request.json)
    return jsonify({"status": "ok"})

@web_bp.route('/api/save_template', methods=['POST'])
def api_save_template():
    if not session.get('logged_in'): return "403", 403
    sys = get_conf('system', DEFAULT_SYSTEM)
    sys['template'] = request.json.get('template')
    set_conf('system', sys)
    return jsonify({"status": "ok"})

@web_bp.route('/api/save_system', methods=['POST'])
def api_save_system():
    if not session.get('logged_in'): return "403", 403
    curr = get_conf('system', DEFAULT_SYSTEM)
    curr.update(request.json)
    set_conf('system', curr)
    return jsonify({"status": "ok"})

@web_bp.route('/api/push_user', methods=['POST'])
def api_push_user():
    """推送功能 (截图8)"""
    if not session.get('logged_in'): return "403", 403
    # 需要在 app/__init__.py 里定义 global_bot
    from . import global_bot, global_loop
    
    uid = request.json.get('id')
    user = User.query.filter_by(id=uid).first()
    sys = get_conf('system', DEFAULT_SYSTEM)
    channel = sys.get('push_channel_id')
    
    if not channel: return jsonify({"status": "err", "msg": "请先在系统设置填写推送频道ID"})
    
    tpl = sys.get('template', '')
    fields_map = {f['key']: f['label'] for f in get_conf('fields', DEFAULT_FIELDS)}
    
    try:
        data = json.loads(user.profile_data)
        line = tpl.replace("{onlineEmoji}", sys['online_emoji'] if user.online else sys['offline_emoji'])
        for k, v in data.items():
            if k in fields_map: line = line.replace(f"{{{fields_map[k]}}}", str(v))
        line = re.sub(r'\{.*?\}', '', line)
        
        if global_bot and global_loop:
            asyncio.run_coroutine_threadsafe(
                global_bot.send_message(chat_id=channel, text=line, parse_mode='HTML'),
                global_loop
            )
            return jsonify({"status": "ok"})
    except Exception as e: return jsonify({"status": "err", "msg": str(e)})
    return jsonify({"status": "err", "msg": "Bot未连接"})

@web_bp.route('/magic_login')
def magic_login():
    token = request.args.get('token')
    if token and jwt.decode(token, os.getenv('SECRET_KEY'), algorithms=['HS256']).get('uid') == int(os.getenv('ADMIN_ID')):
        session['logged_in'] = True
        return redirect('/')
    return "Error", 403

@web_bp.route('/logout')
def logout(): session.clear(); return redirect('/')
