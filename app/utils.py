from .models import Config, db
import json

def get_conf(key, default):
    c = Config.query.filter_by(key=key).first()
    return json.loads(c.value) if c else default

def set_conf(key, value):
    c = Config.query.filter_by(key=key).first()
    if not c:
        c = Config(key=key)
        db.session.add(c)
    if isinstance(value, (dict, list)):
        c.value = json.dumps(value, ensure_ascii=False)
    else:
        c.value = str(value)
    db.session.commit()
