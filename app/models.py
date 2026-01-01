from . import db
from datetime import datetime
import json

class Config(db.Model):
    """全局配置"""
    key = db.Column(db.String(50), primary_key=True)
    value = db.Column(db.Text)

class User(db.Model):
    """用户表"""
    __tablename__ = 'users_v1'
    id = db.Column(db.Integer, primary_key=True)
    tg_id = db.Column(db.BigInteger, unique=True, index=True)
    profile_data = db.Column(db.Text, default='{}')
    expiration_date = db.Column(db.DateTime)
    points = db.Column(db.Integer, default=0)
    checkin_time = db.Column(db.DateTime)
    online = db.Column(db.Boolean, default=False)
    # 记录最后打卡群ID
    last_chat_id = db.Column(db.String(50)) 
    
    @property
    def is_expired(self):
        return self.expiration_date and datetime.now() > self.expiration_date

class BotGroup(db.Model):
    """群组/频道表 (替代旧的 Chat 表)"""
    __tablename__ = 'bot_groups'
    id = db.Column(db.Integer, primary_key=True)
    chat_id = db.Column(db.String(50), unique=True, index=True)
    title = db.Column(db.String(255))
    type = db.Column(db.String(50))
    is_active = db.Column(db.Boolean, default=True) 
    config = db.Column(db.Text, default='{}') # 独立配置
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

# 默认字段
DEFAULT_FIELDS = [
    {"key": "name", "label": "昵称", "type": "text"},
    {"key": "region", "label": "地区", "type": "select", "options": ["区域A","区域B"]},
    {"key": "price", "label": "等级", "type": "text"},
]

# 全局系统默认配置
DEFAULT_SYSTEM = {
    "checkin_open": True,
    "checkin_cmd": "打卡",
    "query_cmd": "查询",
    "del_time": 30,
    "online_emoji": "🟢",
    "offline_emoji": "🔴",
    "auto_like": True,
    "like_emoji": "❤️",
    "msg_checkin_success": "✅ <b>打卡成功！</b>",
    "msg_not_registered": "⚠️ <b>未认证用户</b>",
    "msg_repeat_checkin": "🔄 <b>今天已打卡</b>",
    "msg_query_header": "🔍 <b>今日在线：</b>\n",
    "template": "{onlineEmoji} {昵称} | {地区}",
    "push_channel_id": ""
}

# 群组独立配置默认值 (与系统一致)
DEFAULT_CHAT_SETTINGS = DEFAULT_SYSTEM.copy()
