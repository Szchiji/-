from . import db
from datetime import datetime
import json

# 全局配置 (保留用于字段定义等不随群变化的配置)
class Config(db.Model):
    key = db.Column(db.String(50), primary_key=True)
    value = db.Column(db.Text)

class User(db.Model):
    __tablename__ = 'users_v2' # 升级版本号
    id = db.Column(db.Integer, primary_key=True)
    tg_id = db.Column(db.BigInteger, unique=True, index=True)
    profile_data = db.Column(db.Text, default='{}') 
    checkin_time = db.Column(db.DateTime)
    online = db.Column(db.Boolean, default=False)
    # 记录用户最后一次在哪个群打卡 (可选)
    last_chat_id = db.Column(db.BigInteger)

class Chat(db.Model):
    __tablename__ = 'chats_v2' # 升级版本号
    id = db.Column(db.BigInteger, primary_key=True) # Chat ID
    title = db.Column(db.String(255))
    type = db.Column(db.String(50)) # group/supergroup/channel
    
    # 🌟 核心：每个群独立的配置 (JSON格式存储)
    # 包含：checkin_open, checkin_cmd, auto_like, msg_xxx 等所有配置
    settings = db.Column(db.Text, default='{}')

    def get_setting(self, key, default=None):
        try:
            s = json.loads(self.settings or '{}')
            return s.get(key, default)
        except:
            return default

# 默认字段配置 (全局共用)
DEFAULT_FIELDS = [
    {"key": "name", "label": "昵称", "type": "text"},
    {"key": "region", "label": "地区", "type": "select", "options": ["福田","南山"]},
    {"key": "level", "label": "等级", "type": "text"},
]

# 默认群组配置模板
DEFAULT_CHAT_SETTINGS = {
    "checkin_open": True,
    "checkin_cmd": "打卡",
    "query_cmd": "查询",
    "auto_like": True,
    "like_emoji": "❤️",
    "del_time": 30,
    "online_emoji": "🟢",
    "msg_success": "✅ <b>打卡成功</b>",
    "msg_repeat": "🔄 <b>今日已打卡</b>",
    "msg_fail": "⚠️ <b>未认证</b>",
    "msg_query_head": "🔍 <b>今日在线：</b>\n",
    "user_template": "{onlineEmoji} {昵称Value} | {地区Value}"
}
