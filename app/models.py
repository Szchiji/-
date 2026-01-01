from . import db
from datetime import datetime

class Config(db.Model):
    """通用配置表"""
    key = db.Column(db.String(50), primary_key=True)
    value = db.Column(db.Text)

class User(db.Model):
    """用户表"""
    __tablename__ = 'users_v1'
    id = db.Column(db.Integer, primary_key=True)
    tg_id = db.Column(db.BigInteger, unique=True, index=True)
    profile_data = db.Column(db.Text, default='{}') # JSON 存储资料
    expiration_date = db.Column(db.DateTime)
    points = db.Column(db.Integer, default=0)
    checkin_time = db.Column(db.DateTime)
    online = db.Column(db.Boolean, default=False)
    
    @property
    def is_expired(self):
        return self.expiration_date and datetime.now() > self.expiration_date

# --- 默认配置 ---
DEFAULT_FIELDS = [
    {"key": "name", "label": "昵称", "type": "text"},
    {"key": "region", "label": "地区", "type": "select", "options": ["区域A","区域B"]},
    {"key": "price", "label": "等级", "type": "text"},
]

DEFAULT_SYSTEM = {
    # --- 打卡配置 ---
    "checkin_open": True,
    "checkin_cmd": "打卡",
    "online_emoji": "🟢",
    "offline_emoji": "🔴",
    "auto_like": True,
    "like_emoji": "❤️",
    "checkin_del_time": 30,
    
    # 消息提示
    "msg_checkin_success": "✅ <b>打卡成功！</b>",
    "msg_not_registered": "⚠️ <b>未认证用户无法操作</b>",
    "msg_repeat_checkin": "🔄 <b>今天已打卡</b>",
    "msg_checkin_cancel": "🛑 <b>状态已重置</b>",
    
    # --- 查询配置 ---
    "query_open": True,
    "query_cmd": "查询",
    "query_del_time": 30,
    "msg_query_header": "🔍 <b>今日在线：</b>\n",
    "template": "<b>{onlineEmoji} {昵称}</b> | {地区}",
    "page_size": 10,
    "online_delay": 0,
    "push_channel_id": ""
}
