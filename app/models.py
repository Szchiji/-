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
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

class GroupUser(db.Model):
    __tablename__ = 'group_users'
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('bot_groups.id'), index=True)
    tg_id = db.Column(db.BigInteger)
    profile_data = db.Column(db.Text, default='{}')
    expiration_date = db.Column(db.DateTime)
    checkin_time = db.Column(db.DateTime)
    online = db.Column(db.Boolean, default=False)
    __table_args__ = (db.UniqueConstraint('group_id', 'tg_id', name='_group_user_uc'),)

    @property
    def is_expired(self):
        return self.expiration_date and datetime.now() > self.expiration_date

DEFAULT_FIELDS = [
    {"key": "name", "label": "昵称", "type": "text"},
    {"key": "region", "label": "地区", "type": "select", "options": ["福田","南山"]},
    {"key": "level", "label": "等级", "type": "text"},
]

DEFAULT_SYSTEM = {
    "checkin_open": True, "checkin_cmd": "打卡", "query_cmd": "查询", "del_time": 30,
    "online_emoji": "🟢", "offline_emoji": "🔴", "auto_like": True, "like_emoji": "❤️",
    "msg_checkin_success": "✅ <b>打卡成功！</b>", 
    "msg_not_registered": "⚠️ <b>未认证用户</b>",
    "msg_repeat_checkin": "🔄 <b>今天已打卡</b>", 
    "msg_query_header": "🔍 <b>今日在线：</b>\n",
    "template": "{onlineEmoji} {昵称} | {地区}",
    # 🆕 新增：推送专用模板
    "push_template": "<b>👤 用户名片推送</b>\n\n📛 昵称：{昵称}\n📍 地区：{地区}\n💎 等级：{等级}\n\n👉 联系我：<a href='tg://user?id={tg_id}'>点击私聊</a>"
}
