from . import db
from datetime import datetime
import json

class Config(db.Model):
    key = db.Column(db.String(50), primary_key=True)
    value = db.Column(db.Text)

class User(db.Model):
    __tablename__ = 'cms_users_split_v1' # 确保新表
    id = db.Column(db.Integer, primary_key=True)
    tg_id = db.Column(db.BigInteger, unique=True, index=True)
    # 存JSON: {name, price, region...}
    profile_data = db.Column(db.Text, default='{}') 
    expiration_date = db.Column(db.DateTime)
    points = db.Column(db.Integer, default=0)
    checkin_time = db.Column(db.DateTime)
    online = db.Column(db.Boolean, default=False)
    
    @property
    def is_expired(self):
        return self.expiration_date and datetime.now() > self.expiration_date

# 默认字段配置 (截图9)
DEFAULT_FIELDS = [
    {"key": "name", "label": "老师名字", "type": "text", "search": True},
    {"key": "link", "label": "频道链接", "type": "text", "search": True},
    {"key": "region", "label": "地区", "type": "select", "options": ["福田","南山","罗湖","宝安"], "search": True},
    {"key": "price", "label": "价位", "type": "text", "search": True},
    {"key": "cup", "label": "胸围", "type": "select", "options": ["胸A","胸B","胸C"], "search": True},
    {"key": "tags", "label": "服务类型", "type": "checkbox", "options": ["课表","上门"], "search": False},
]

# 默认系统配置 (截图2, 10)
DEFAULT_SYSTEM = {
    "checkin_open": True, "checkin_cmd": "/daka",
    "query_open": True, "query_cmd": "/online",
    "online_emoji": "🟢", "offline_emoji": "🔴",
    "push_channel_id": "", 
    "auto_like": True, "like_emoji": "💯",
    "template": "<b>{onlineEmoji} {老师名字}</b>\n💰 {价位}\n📍 {地区}"
}
