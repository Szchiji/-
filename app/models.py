from . import db
from datetime import datetime
import json

class BotGroup(db.Model):
    """群组/频道表 (核心租户表)"""
    __tablename__ = 'bot_groups'
    id = db.Column(db.Integer, primary_key=True)
    chat_id = db.Column(db.String(50), unique=True, index=True) # 真实的 TG Chat ID
    title = db.Column(db.String(255))
    type = db.Column(db.String(50))
    is_active = db.Column(db.Boolean, default=True)
    
    # 独立配置 (JSON)
    config = db.Column(db.Text, default='{}')
    # 独立字段定义 (JSON)，默认为全局字段
    fields_config = db.Column(db.Text) 
    
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

class GroupUser(db.Model):
    """群组专属用户表 (取代全局 User 表)"""
    __tablename__ = 'group_users'
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('bot_groups.id'), index=True) # 关联到 BotGroup
    tg_id = db.Column(db.BigInteger)
    
    profile_data = db.Column(db.Text, default='{}') # 本群的资料
    expiration_date = db.Column(db.DateTime)
    checkin_time = db.Column(db.DateTime)
    online = db.Column(db.Boolean, default=False)
    
    # 联合唯一索引：确保同一个群里 tg_id 唯一
    __table_args__ = (db.UniqueConstraint('group_id', 'tg_id', name='_group_user_uc'),)

    @property
    def is_expired(self):
        return self.expiration_date and datetime.now() > self.expiration_date

# 默认全局配置 (仅作新群初始值)
DEFAULT_FIELDS = [
    {"key": "name", "label": "昵称", "type": "text"},
    {"key": "region", "label": "地区", "type": "select", "options": ["区域A","区域B"]},
    {"key": "price", "label": "等级", "type": "text"},
]

DEFAULT_SYSTEM = {
    "checkin_open": True,
    "checkin_cmd": "打卡",
    "online_emoji": "🟢",
    "offline_emoji": "🔴",
    "auto_like": True,
    "like_emoji": "❤️",
    "checkin_del_time": 30,
    "msg_checkin_success": "✅ <b>打卡成功！</b>",
    "msg_not_registered": "⚠️ <b>未认证用户</b>",
    "msg_repeat_checkin": "🔄 <b>今天已打卡</b>",
    "query_open": True,
    "query_cmd": "查询",
    "query_del_time": 30,
    "msg_query_header": "🔍 <b>今日在线：</b>\n",
    "template": "{onlineEmoji} {昵称} | {地区}",
}
