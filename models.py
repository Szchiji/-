from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    telegram_id = db.Column(db.BigInteger, unique=True, index=True)
    username = db.Column(db.String(100))
    # 会员业务字段
    membership_id = db.Column(db.String(50))
    level = db.Column(db.String(20), default='E')
    expiration_date = db.Column(db.DateTime)
    # 状态字段
    checkin_time = db.Column(db.DateTime)
    online = db.Column(db.Boolean, default=False)
    points = db.Column(db.Integer, default=0)
    
    @property
    def is_expired(self):
        if not self.expiration_date: return True
        return datetime.now() > self.expiration_date

class AutoReply(db.Model):
    __tablename__ = 'auto_replies'
    id = db.Column(db.Integer, primary_key=True)
    keyword = db.Column(db.String(255))
    reply_text = db.Column(db.Text)
