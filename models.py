from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

# 用户表
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    telegram_id = db.Column(db.BigInteger, unique=True, nullable=False)
    username = db.Column(db.String(100))
    # 会员信息
    membership_level = db.Column(db.String(20), default='E')  # A, B, E
    expiration_date = db.Column(db.DateTime)  # 过期时间
    points = db.Column(db.Integer, default=0) # 积分
    # 状态
    is_online = db.Column(db.Boolean, default=False)
    last_checkin = db.Column(db.DateTime)
    
    def __repr__(self):
        return f'<User {self.telegram_id}>'

# 自动回复规则表
class AutoReply(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    keyword = db.Column(db.String(100), nullable=False)
    reply_content = db.Column(db.Text, nullable=False)
    match_type = db.Column(db.String(20), default='exact') # exact, contains
