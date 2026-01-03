from flask import Flask
from flask_sqlalchemy import SQLAlchemy
import os
import json

db = SQLAlchemy()

# 全局变量
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
    
    # SECRET_KEY 配置 - 生产环境必须设置
    secret_key = os.getenv('SECRET_KEY', 'default_secret_key')
    if secret_key == 'default_secret_key':
        print("⚠️ WARNING: Using default SECRET_KEY. Please set SECRET_KEY environment variable for production!", flush=True)
    app.config['SECRET_KEY'] = secret_key
    
    db.init_app(app)
    
    # 注册过滤器
    @app.template_filter('from_json')
    def from_json_filter(value):
        try: return json.loads(value)
        except: return {}

    # 📦 注册模块
    from app.modules.core.routes import core_bp
    app.register_blueprint(core_bp)
    
    return app
