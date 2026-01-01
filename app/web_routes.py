from flask import Blueprint, render_template, request, redirect, session, render_template_string
from .models import db, Member, SystemConfig
from .utils import get_conf, set_conf
from .models import DEFAULT_FIELDS
import json
import jwt
import os
import time

web_bp = Blueprint('web', __name__)

# --- 嵌入式 HTML 模板 (为了方便部署，把 HTML 放变量里，也可以放 templates 文件夹) ---
# 这里为了简洁，我引用外部文件，实际部署时请创建 app/templates/admin_base.html
# 下面代码会读取该文件

@web_bp.route('/')
def index():
    if not session.get('logged_in'):
        return render_template('admin_base.html', page='login')
        
    page = request.args.get('tab', 'users')
    
    # 数据准备
    data = {}
    if page == 'users':
        limit = int(request.args.get('limit', 10))
        data['users'] = Member.query.order_by(Member.id.desc()).limit(limit).all()
        
    elif page == 'fields':
        data['fields'] = get_conf('fields', DEFAULT_FIELDS)
        data['fields_json'] = json.dumps(data['fields'], ensure_ascii=False)
        
    elif page == 'template':
        data['template'] = get_conf('msg_template', "<b>{onlineEmoji} {老师名字}</b>\n💰 {价位}")
        data['fields'] = get_conf('fields', DEFAULT_FIELDS)
        
    elif page == 'system':
        data['sys'] = get_conf('system_settings', {
            "checkin_open": True, "query_open": True, 
            "online_emoji": "🟢", "offline_emoji": "🔴"
        })

    return render_template('admin_base.html', page=page, **data)

@web_bp.route('/magic_login')
def magic_login():
    token = request.args.get('token')
    try:
        payload = jwt.decode(token, os.getenv('SECRET_KEY'), algorithms=['HS256'])
        if payload['uid'] == int(os.getenv('ADMIN_ID')):
            session['logged_in'] = True
            return redirect('/?tab=users')
    except: pass
    return "Login Failed", 403

# --- 增删改查 API ---

@web_bp.route('/save_fields', methods=['POST'])
def save_fields():
    if session.get('logged_in'):
        fields = json.loads(request.form.get('fields_json'))
        set_conf('fields', fields)
    return redirect('/?tab=fields')

@web_bp.route('/save_template', methods=['POST'])
def save_template():
    if session.get('logged_in'):
        set_conf('msg_template', request.form.get('template'))
    return redirect('/?tab=template')

@web_bp.route('/update_user', methods=['POST'])
def update_user():
    if not session.get('logged_in'): return redirect('/')
    
    tg_id = int(request.form.get('tg_id'))
    u = Member.query.filter_by(tg_id=tg_id).first()
    if not u:
        u = Member(tg_id=tg_id)
        db.session.add(u)
    
    # 动态字段处理
    fields = get_conf('fields', DEFAULT_FIELDS)
    profile = {}
    for f in fields:
        k = f['key']
        if f['type'] == 'checkbox':
            profile[k] = ",".join(request.form.getlist(f"field_{k}"))
        else:
            profile[k] = request.form.get(f"field_{k}", "")
            
    u.profile_data = json.dumps(profile, ensure_ascii=False)
    db.session.commit()
    return redirect('/?tab=users')

@web_bp.route('/del_user/<int:id>')
def del_user(id):
    if session.get('logged_in'):
        Member.query.filter_by(id=id).delete()
        db.session.commit()
    return redirect('/?tab=users')

@web_bp.route('/logout')
def logout():
    session.clear()
    return redirect('/')
