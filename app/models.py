from . import db
from datetime import datetime

class Config(db.Model):
    key = db.Column(db.String(50), primary_key=True)
    value = db.Column(db.Text)

class User(db.Model):
    __tablename__ = 'cms_users_split_v1'
    id = db.Column(db.Integer, primary_key=True)
    tg_id = db.Column(db.BigInteger, unique=True, index=True)
    profile_data = db.Column(db.Text, default='{}') # JSON
    expiration_date = db.Column(db.DateTime)
    points = db.Column(db.Integer, default=0)
    checkin_time = db.Column(db.DateTime)
    online = db.Column(db.Boolean, default=False)
    
    @property
    def is_expired(self):
        return self.expiration_date and datetime.now() > self.expiration_date

# 默认配置
DEFAULT_FIELDS = [
    {"key": "name", "label": "老师名字", "type": "text"},
    {"key": "region", "label": "地区", "type": "select", "options": ["福田","南山","罗湖","宝安"]},
    {"key": "price", "label": "价位", "type": "text"},
]
DEFAULT_SYSTEM = {
    "checkin_open": True, "checkin_cmd": "/daka",
    "query_open": True, "query_cmd": "/online",
    "online_emoji": "🟢", "offline_emoji": "🔴",
    "auto_like": True, "like_emoji": "💯",
    "push_channel_id": ""
}
