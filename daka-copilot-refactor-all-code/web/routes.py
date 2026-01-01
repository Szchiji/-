from flask import render_template, request, redirect, url_for, jsonify, session, flash
from flask_login import login_user, login_required, logout_user, current_user
from werkzeug.security import check_password_hash
from flask_jwt_extended import jwt_required, get_jwt_identity, create_access_token, decode_token
from models import db, User, Config, AdminUser, AutoReply, ReplyLog, ScheduledMessage, ForceSubscribe, Points, Item, Button
from config import SIDEBAR_MENU, ADMIN_ID
from datetime import datetime
import json
import logging

logger = logging.getLogger(__name__)

def init_routes(app):
    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if request.method == 'POST':
            username = request.form['username']
            password = request.form['password']
            user = AdminUser.query.filter_by(username=username).first()
            if user and check_password_hash(user.password, password):
                login_user(user)
                return redirect(url_for('index'))
            else:
                flash('用户名或密码错误')
        return render_template('login.html')

    @app.route('/magic_login')
    def magic_login():
        token = request.args.get('token')
        if not token:
            return "Missing token", 400
        
        try:
            # Decode and verify the token
            decoded = decode_token(token)
            identity = decoded.get('sub')
            
            # Verify identity matches ADMIN_ID (ensure type consistency)
            if str(identity) != str(ADMIN_ID):
                return "Invalid identity", 403
                
            # Log the user in
            # Assuming there is only one admin user 'admin' for now, or fetch by ID if your AdminUser supports it
            user = AdminUser.query.filter_by(username='admin').first()
            if not user:
                 # Fallback: create admin if missing (though app.py usually handles this)
                 return "Admin user not found in DB", 500
            
            login_user(user)
            return redirect(url_for('index'))
            
        except Exception as e:
            logger.error(f"Magic login failed: {e}")
            return f"Invalid or expired token: {str(e)}", 401

    @app.route('/logout')
    @login_required
    def logout():
        logout_user()
        return redirect(url_for('login'))

    @app.route('/')
    @login_required
    def index():
        group_id = request.args.get('group_id') or session.get('current_group')
        if group_id:
            session['current_group'] = group_id
        users = User.query.filter_by(group_id=session.get('current_group')).all()
        return render_template('base.html', sidebar=SIDEBAR_MENU, content='index', users=users)

    # API Route: Keep JWT for programmatic access if needed, but not for browser views
    @app.route('/refresh', methods=['POST'])
    @jwt_required(refresh=True)
    def refresh():
        identity = get_jwt_identity()
        access_token = create_access_token(identity=identity)
        return jsonify(access_token=access_token)

    @app.route('/auth_config')
    @login_required
    def auth_config():
        fields = ['培训字幕', '用户链接', '培训通道', '等级', '价格', '地区', '类型', '图片']
        return render_template('base.html', sidebar=SIDEBAR_MENU, content='auth_config', fields=fields)

    @app.route('/add_user', methods=['GET', 'POST'])
    @login_required
    def add_user():
        if request.method == 'POST':
            try:
                telegram_id = int(request.form.get('telegram_id', 0))
                membership_id = int(request.form['membership_id'])
                upgrade_count = int(request.form['upgrade_count'])
                training_title = request.form['training_title']
                training_link = request.form['training_link']
                training_channel = request.form['training_channel']
                level = request.form['level']
                price = float(request.form['price'])
                region = request.form['region']
                types = ','.join(request.form.getlist('types'))
                image_url = request.form['image_url']
                expiration_date = datetime.strptime(request.form['expiration_date'], '%Y-%m-%d') if request.form['expiration_date'] else None
                group_id = session.get('current_group')
                user = User(telegram_id=telegram_id, membership_id=membership_id, upgrade_count=upgrade_count, training_title=training_title, 
                            training_link=training_link, training_channel=training_channel, level=level, price=price, 
                            region=region, types=types, image_url=image_url, expiration_date=expiration_date, group_id=group_id)
                db.session.add(user)
                db.session.commit()
                return redirect(url_for('index'))
            except Exception as e:
                flash(f"添加失败: {e}")
        return render_template('base.html', sidebar=SIDEBAR_MENU, content='add_user')

    @app.route('/preview_template', methods=['POST'])
    @login_required
    def preview_template():
        template = request.form['template']
        data = {'onlineEmoji': '🟢', 'Value': '示例名字', '价格Value': '900p'}
        try:
            preview = template.format(**data)
        except Exception:
            preview = template
        return jsonify({'preview': preview})

    @app.route('/auto_reply')
    @login_required
    def auto_reply():
        group_id = session.get('current_group')
        rules = AutoReply.query.filter_by(group_id=group_id).order_by(AutoReply.priority.desc()).all()
        logs = ReplyLog.query.all()
        return render_template('base.html', sidebar=SIDEBAR_MENU, content='auto_reply', rules=rules, logs=logs)

    @app.route('/auto_reply/add', methods=['POST'])
    @login_required
    def add_auto_reply():
        keyword = request.form['keyword']
        reply_text = request.form['reply_text']
        match_type = request.form['match_type']
        enabled = bool(request.form.get('enabled', False))
        media_type = request.form.get('media_type', None)
        media_url = request.form.get('media_url', None)
        caption = request.form.get('caption', None)
        has_spoiler = bool(request.form.get('has_spoiler', False))
        priority = int(request.form.get('priority', 0))
        status = request.form.get('status', 'active')
        buttons_json = request.form.get('buttons', '[]')
        group_id = session.get('current_group')
        rule = AutoReply(keyword=keyword, reply_text=reply_text, match_type=match_type, enabled=enabled, 
                         media_type=media_type, media_url=media_url, caption=caption, has_spoiler=has_spoiler, 
                         priority=priority, status=status, group_id=group_id)
        db.session.add(rule)
        db.session.commit()
        for btn in json.loads(buttons_json):
            button = Button(text=btn['text'], url=btn.get('url'), callback_data=btn.get('callback_data'), reply_id=rule.id)
            db.session.add(button)
        db.session.commit()
        return redirect(url_for('auto_reply'))

    @app.route('/auto_reply/update/<int:rule_id>', methods=['POST'])
    @login_required
    def update_auto_reply(rule_id):
        rule = AutoReply.query.get(rule_id)
        if rule:
            rule.keyword = request.form['keyword']
            rule.reply_text = request.form['reply_text']
            rule.match_type = request.form['match_type']
            rule.enabled = bool(request.form.get('enabled', False))
            rule.media_type = request.form.get('media_type', None)
            rule.media_url = request.form.get('media_url', None)
            rule.caption = request.form.get('caption', None)
            rule.has_spoiler = bool(request.form.get('has_spoiler', False))
            rule.priority = int(request.form.get('priority', 0))
            rule.status = request.form.get('status', 'active')
            db.session.commit()
        return redirect(url_for('auto_reply'))

    @app.route('/auto_reply/delete/<int:rule_id>')
    @login_required
    def delete_auto_reply(rule_id):
        rule = AutoReply.query.get(rule_id)
        if rule:
            db.session.delete(rule)
            db.session.commit()
        return redirect(url_for('auto_reply'))

    @app.route('/auto_reply/toggle/<int:rule_id>', methods=['POST'])
    @login_required
    def toggle_auto_reply(rule_id):
        rule = AutoReply.query.get(rule_id)
        if rule:
            rule.status = 'inactive' if rule.status == 'active' else 'active'
            db.session.commit()
            return jsonify({'status': rule.status})
        return jsonify({'error': 'Rule not found'}), 404

    @app.route('/auto_reply/preview/<int:rule_id>')
    @login_required
    def preview_auto_reply(rule_id):
        rule = AutoReply.query.get(rule_id)
        if rule:
            preview = rule.reply_text  # 或模拟媒体
            return jsonify({'preview': preview})
        return jsonify({'error': '规则不存在'})

    @app.route('/auto_reply/export/<int:rule_id>')
    @login_required
    def export_auto_reply_log(rule_id):
        logs = ReplyLog.query.filter_by(rule_id=rule_id).all()
        import csv
        from io import StringIO
        si = StringIO()
        cw = csv.writer(si)
        cw.writerow(['ID', '用户ID', '时间', '次数'])
        for log in logs:
            cw.writerow([log.id, log.user_id, log.timestamp, log.count])
        return si.getvalue(), 200, {'Content-Type': 'text/csv', 'Content-Disposition': 'attachment; filename=log.csv'}

    @app.route('/scheduled')
    @login_required
    def scheduled():
        group_id = session.get('current_group')
        tasks = ScheduledMessage.query.filter_by(group_id=group_id).all()
        return render_template('base.html', sidebar=SIDEBAR_MENU, content='scheduled', tasks=tasks)

    @app.route('/scheduled/add', methods=['POST'])
    @login_required
    def add_scheduled():
        chat_id = int(request.form['chat_id'])
        message_text = request.form['message_text']
        schedule_time = request.form['schedule_time']
        enabled = bool(request.form.get('enabled', False))
        media_type = request.form.get('media_type', None)
        media_url = request.form.get('media_url', None)
        caption = request.form.get('caption', None)
        timezone = request.form.get('timezone', 'UTC')
        silent = bool(request.form.get('silent', False))
        retry_count = int(request.form.get('retry_count', 3))
        condition = request.form.get('condition', None)
        buttons_json = request.form.get('buttons', '[]')
        group_id = session.get('current_group')
        task = ScheduledMessage(chat_id=chat_id, message_text=message_text, schedule_time=schedule_time, enabled=enabled, 
                                media_type=media_type, media_url=media_url, caption=caption, timezone=timezone, 
                                silent=silent, retry_count=retry_count, condition=condition, group_id=group_id)
        db.session.add(task)
        db.session.commit()
        for btn in json.loads(buttons_json):
            button = Button(text=btn['text'], url=btn.get('url'), callback_data=btn.get('callback_data'), scheduled_id=task.id)
            db.session.add(button)
        db.session.commit()
        return redirect(url_for('scheduled'))

    @app.route('/scheduled/update/<int:task_id>', methods=['POST'])
    @login_required
    def update_scheduled(task_id):
        task = ScheduledMessage.query.get(task_id)
        if task:
            task.chat_id = int(request.form['chat_id'])
            task.message_text = request.form['message_text']
            task.schedule_time = request.form['schedule_time']
            task.enabled = bool(request.form.get('enabled', False))
            task.media_type = request.form.get('media_type', None)
            task.media_url = request.form.get('media_url', None)
            task.caption = request.form.get('caption', None)
            task.timezone = request.form.get('timezone', 'UTC')
            task.silent = bool(request.form.get('silent', False))
            task.retry_count = int(request.form.get('retry_count', 3))
            task.condition = request.form.get('condition', None)
            db.session.commit()
        return redirect(url_for('scheduled'))

    @app.route('/scheduled/delete/<int:task_id>')
    @login_required
    def delete_scheduled(task_id):
        task = ScheduledMessage.query.get(task_id)
        if task:
            db.session.delete(task)
            db.session.commit()
        return redirect(url_for('scheduled'))

    @app.route('/force_subscribe')
    @login_required
    def force_subscribe():
        group_id = session.get('current_group')
        rules = ForceSubscribe.query.filter_by(group_id=group_id).all()
        
        # Safe access to config values
        auto_unmute_cfg = Config.query.filter_by(key='auto_unmute_enabled', group_id=group_id).first()
        auto_unmute = auto_unmute_cfg.value if auto_unmute_cfg else 'False'
        
        unmute_msg_cfg = Config.query.filter_by(key='unmute_message', group_id=group_id).first()
        unmute_message = unmute_msg_cfg.value if unmute_msg_cfg else '订阅完成！'
        
        return render_template('base.html', sidebar=SIDEBAR_MENU, content='force_subscribe', rules=rules, auto_unmute=auto_unmute, unmute_message=unmute_message)

    @app.route('/force_subscribe/update_settings', methods=['POST'])
    @login_required
    def update_force_subscribe_settings():
        group_id = session.get('current_group')
        
        # Helper to merge config
        def merge_config(key, value):
            existing = Config.query.filter_by(key=key, group_id=group_id).first()
            if existing:
                existing.value = value
            else:
                db.session.add(Config(key=key, value=value, group_id=group_id))
        
        merge_config('auto_unmute_enabled', request.form['auto_unmute_enabled'])
        merge_config('unmute_message', request.form['unmute_message'])
        
        db.session.commit()
        return redirect(url_for('force_subscribe'))

    @app.route('/force_subscribe/add', methods=['POST'])
    @login_required
    def add_force_subscribe():
        target_id = int(request.form['target_id'])
        type_ = request.form['type']
        reminder_text = request.form['reminder_text']
        action = request.form['action']
        enabled = bool(request.form.get('enabled', False))
        check_timing = request.form['check_timing']
        verify_frequency = request.form['verify_frequency']
        timed_verify_enabled = bool(request.form.get('timed_verify_enabled', False))
        timed_verify_cron = request.form['timed_verify_cron']
        timed_verify_scope = request.form['timed_verify_scope']
        group_id = session.get('current_group')
        rule = ForceSubscribe(target_id=target_id, type=type_, reminder_text=reminder_text, action=action, 
                              enabled=enabled, check_timing=check_timing, verify_frequency=verify_frequency, 
                              timed_verify_enabled=timed_verify_enabled, timed_verify_cron=timed_verify_cron, 
                              timed_verify_scope=timed_verify_scope, group_id=group_id)
        db.session.add(rule)
        db.session.commit()
        return redirect(url_for('force_subscribe'))

    @app.route('/force_subscribe/update/<int:rule_id>', methods=['POST'])
    @login_required
    def update_force_subscribe(rule_id):
        rule = ForceSubscribe.query.get(rule_id)
        if rule:
            rule.target_id = int(request.form['target_id'])
            rule.type = request.form['type']
            rule.reminder_text = request.form['reminder_text']
            rule.action = request.form['action']
            rule.enabled = bool(request.form.get('enabled', False))
            rule.check_timing = request.form['check_timing']
            rule.verify_frequency = request.form['verify_frequency']
            rule.timed_verify_enabled = bool(request.form.get('timed_verify_enabled', False))
            rule.timed_verify_cron = request.form['timed_verify_cron']
            rule.timed_verify_scope = request.form['timed_verify_scope']
            db.session.commit()
        return redirect(url_for('force_subscribe'))

    @app.route('/force_subscribe/delete/<int:rule_id>')
    @login_required
    def delete_force_subscribe(rule_id):
        rule = ForceSubscribe.query.get(rule_id)
        if rule:
            db.session.delete(rule)
            db.session.commit()
        return redirect(url_for('force_subscribe'))

    @app.route('/points_config')
    @login_required
    def points_config():
        items = Item.query.all()
        return render_template('base.html', sidebar=SIDEBAR_MENU, content='points_config', items=items)

    @app.route('/points/add_item', methods=['POST'])
    @login_required
    def add_item():
        name = request.form['name']
        cost = int(request.form['cost'])
        description = request.form['description']
        stock = int(request.form.get('stock', 10))
        item = Item(name=name, cost=cost, description=description, stock=stock)
        db.session.add(item)
        db.session.commit()
        return redirect(url_for('points_config'))
