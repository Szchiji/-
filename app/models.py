
from . import db
from datetime import datetime
import json

class SystemConfig(db.Model):
    """通用配置表，存储所有开关和设置"""
    key = db.Column(db.String(50), primary_key=True)
    value = db.Column(db.Text) # JSON 格式存储

class Member(db.Model):
    """认证用户表"""
    __tablename__ = 'members'
    id = db.Column(db.Integer, primary_key=True)
    tg_id = db.Column(db.BigInteger, unique=True, index=True)
    username = db.Column(db.String(100))
    
    # 核心动态数据 (存截图里的: 价格, 地区, 罩杯, 链接等)
    # 格式: {"price": "1000", "region": "福田", "tags": ["上门"]}
    profile_data = db.Column(db.Text, default='{}') 
    
    # 业务状态
    points = db.Column(db.Integer, default=0)
    expiration_date = db.Column(db.DateTime)
    last_checkin = db.Column(db.DateTime)
    online = db.Column(db.Boolean, default=False)
    
    # 推送状态 (截图8)
    push_message_id = db.Column(db.Integer) # 记录推送到频道的消息ID

    @property
    def is_expired(self):
        return self.expiration_date and datetime.now() > self.expiration_date

# 默认字段定义 (截图9复刻)
DEFAULT_FIELDS = [
    {"key": "name", "label": "老师名字", "type": "text", "search": True},
    {"key": "link", "label": "频道链接", "type": "text", "search": False},
    {"key": "region", "label": "地区", "type": "select", "options": ["福田","南山","罗湖","宝安"], "search": True},
    {"key": "price", "label": "价位", "type": "text", "search": True},
    {"key": "cup", "label": "胸围", "type": "select", "options": ["C","D","E","F"], "search": True},
    {"key": "tags", "label": "类型", "type": "checkbox", "options": ["短发","长发","学生","御姐"], "search": False}
]
