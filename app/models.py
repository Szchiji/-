from . import db
from datetime import datetime
import json

class BotGroup(db.Model):
    __tablename__ = 'bot_groups'
    id = db.Column(db.Integer, primary_key=True)
    chat_id = db.Column(db.String(50), unique=True, index=True)
    title = db.Column(db.String(255))
    type = db.Column(db.String(50))
    is_active = db.Column(db.Boolean, default=True)
    config = db.Column(db.Text, default='{}')
    fields_config = db.Column(db.Text)
    last_query_msg_id = db.Column(db.Integer, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

class GroupUser(db.Model):
    __tablename__ = 'group_users'
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('bot_groups.id'), index=True)
    tg_id = db.Column(db.BigInteger)
    profile_data = db.Column(db.Text, default='{}')
    
    # 🆕 有效期控制
    expiration_date = db.Column(db.DateTime, nullable=True) # 到期时间
    is_banned = db.Column(db.Boolean, default=False)        # 是否已被机器人禁言
    
    checkin_time = db.Column(db.DateTime)
    online = db.Column(db.Boolean, default=False)
    
    __table_args__ = (db.UniqueConstraint('group_id', 'tg_id', name='_group_user_uc'),)

DEFAULT_FIELDS = [
    {"key": "name", "label": "昵称", "type": "text"},
    {"key": "region", "label": "地区", "type": "select", "options": ["福田","南山"]},
]

DEFAULT_SYSTEM = {
    "checkin_open": True, "checkin_cmd": "打卡", 
    "query_cmd": "查询", "query_filter_open": True,
    "checkin_del_time": 30, 
    "query_del_time": 60,
    "page_size": 10,
    "auto_like": True, "like_emoji": "❤️",
    "push_channel_id": "",
    "msg_checkin_success": "✅ <b>打卡成功！</b>", 
    "msg_not_registered": "⚠️ <b>未认证用户</b>",
    "msg_repeat_checkin": "🔄 <b>今天已打卡</b>", 
    "msg_query_header": "🔍 <b>今日在线用户：</b>\n",
    "msg_filter_header": "🔍 <b>筛选结果：</b>\n",
    "msg_expired_ban": "⛔️ <b>您的认证已过期，已被暂时禁言。请联系管理员续费。</b>", # 🆕 过期提示
    "template": "{onlineEmoji} {昵称} | {地区}",
    "push_template": "<b>👤 名片推送</b>\n昵称：{昵称}\n<a href='tg://user?id={tg_id}'>联系我</a>",
    "custom_btn_text": "", 
    "custom_btn_url": ""
}
