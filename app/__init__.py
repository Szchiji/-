from flask import Flask
from flask_sqlalchemy import SQLAlchemy
import os
import json

db = SQLAlchemy()
global_bot = None
global_loop = None

def create_app():
    app = Flask(__name__)
    
    # 数据库配置
    db_uri = os.getenv('DATABASE_URL', 'sqlite:///bot.db')
    if db_uri and db_uri.startswith("postgres://"):
        db_uri = db_uri.replace("postgres://", "postgresql://", 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = db_uri
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'secret_key_123')
    
    db.init_app(app)
    
    # 注册过滤器
    @app.template_filter('from_json')
    def from_json_filter(value):
        try: return json.loads(value)
        except: return {}

    # 🆕 注册【认证模块】
    from app.modules.certification import cert_bp
    app.register_blueprint(cert_bp)
    
    # 以后可以在这里注册其他模块
    # from app.modules.payment import pay_bp
    # app.register_blueprint(pay_bp)

    return app
