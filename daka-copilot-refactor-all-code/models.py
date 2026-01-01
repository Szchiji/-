from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

db = SQLAlchemy()

class Config(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True)
    value = db.Column(db.String(255))
    group_id = db.Column(db.BigInteger, default=None)  # 新添加 for 多群

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    telegram_id = db.Column(db.BigInteger, unique=True)
    membership_id = db.Column(db.Integer)
    upgrade_count = db.Column(db.Integer, default=0)
    training_title = db.Column(db.String(100))
    training_link = db.Column(db.String(255))
    training_channel = db.Column(db.String(255))
    level = db.Column(db.String(50))
    price = db.Column(db.Float)
    region = db.Column(db.String(50))
    types = db.Column(db.String(255))
    image_url = db.Column(db.String(255))
    checkin_time = db.Column(db.DateTime)
    online = db.Column(db.Boolean, default=False)
    expiration_date = db.Column(db.DateTime, default=None)
    group_id = db.Column(db.BigInteger, default=None)  # 新添加

class AdminUser(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True)
    password = db.Column(db.String(255))

    def set_password(self, password):
        self.password = generate_password_hash(password)

class AutoReply(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    keyword = db.Column(db.String(255))
    reply_text = db.Column(db.Text)
    match_type = db.Column(db.String(50), default='contains')
    enabled = db.Column(db.Boolean, default=True)
    media_type = db.Column(db.String(50), default=None)
    media_url = db.Column(db.String(255), default=None)
    caption = db.Column(db.Text, default=None)
    has_spoiler = db.Column(db.Boolean, default=False)
    priority = db.Column(db.Integer, default=0)
    status = db.Column(db.String(50), default='active')
    group_id = db.Column(db.BigInteger, default=None)  # 新添加

class ReplyLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    rule_id = db.Column(db.Integer)
    user_id = db.Column(db.BigInteger)
    timestamp = db.Column(db.DateTime, default=datetime.now)
    count = db.Column(db.Integer, default=1)

class ScheduledMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    chat_id = db.Column(db.BigInteger)
    message_text = db.Column(db.Text)
    schedule_time = db.Column(db.String(50))
    enabled = db.Column(db.Boolean, default=True)
    media_type = db.Column(db.String(50), default=None)
    media_url = db.Column(db.String(255), default=None)
    caption = db.Column(db.Text, default=None)
    timezone = db.Column(db.String(50), default='UTC')
    silent = db.Column(db.Boolean, default=False)
    retry_count = db.Column(db.Integer, default=3)
    condition = db.Column(db.String(255), default=None)
    group_id = db.Column(db.BigInteger, default=None)  # 新添加

class ForceSubscribe(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    target_id = db.Column(db.BigInteger)
    type = db.Column(db.String(50), default='channel')
    reminder_text = db.Column(db.Text, default='请先订阅频道以加入群组！')
    action = db.Column(db.String(50), default='mute')
    enabled = db.Column(db.Boolean, default=True)
    check_timing = db.Column(db.String(50), default='speak')
    verify_frequency = db.Column(db.String(50), default='per_message')
    timed_verify_enabled = db.Column(db.Boolean, default=False)
    timed_verify_cron = db.Column(db.String(50), default='0 * * * *')
    timed_verify_scope = db.Column(db.String(50), default='all')
    group_id = db.Column(db.BigInteger, default=None)  # 新添加

class Points(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.BigInteger)
    points = db.Column(db.Integer, default=0)
    last_earned = db.Column(db.DateTime)

class Item(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    cost = db.Column(db.Integer)
    description = db.Column(db.Text)
    stock = db.Column(db.Integer, default=10)

class Button(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    text = db.Column(db.String(50))
    url = db.Column(db.String(255), default=None)
    callback_data = db.Column(db.String(255), default=None)
    reply_id = db.Column(db.Integer)
    scheduled_id = db.Column(db.Integer)
