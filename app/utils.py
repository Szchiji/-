from .models import Config, db
import json

def get_conf(key, default):
    c = Config.query.filter_by(key=key).first()
    return json.loads(c.value) if c else default

def set_conf(key, value):
    c = Config.query.filter_by(key=key).first()
    if not c: db.session.add(Config(key=key, value=json.dumps(value, ensure_ascii=False)))
    else: c.value = json.dumps(value, ensure_ascii=False)
    db.session.commit()
