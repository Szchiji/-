from .models import SystemConfig, db, DEFAULT_FIELDS
import json

def get_conf(key, default=None):
    """获取配置，自动处理JSON反序列化"""
    c = SystemConfig.query.get(key)
    if not c: return default
    try:
        return json.loads(c.value)
    except:
        return c.value

def set_conf(key, value):
    """保存配置，自动处理JSON序列化"""
    c = SystemConfig.query.get(key)
    if not c:
        c = SystemConfig(key=key)
        db.session.add(c)
    
    if isinstance(value, (dict, list, bool, int)):
        c.value = json.dumps(value, ensure_ascii=False)
    else:
        c.value = str(value)
    db.session.commit()
