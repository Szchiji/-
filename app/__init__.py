from flask import Flask
from flask_sqlalchemy import SQLAlchemy
import os
import json

db = SQLAlchemy()

# 全局变量用于跨文件调用
global_bot = None
global_loop = None

def create_app():
    app = Flask(__name__)
    
    db_uri = os.getenv('DATABASE_URL', 'sqlite:///bot.db')
    if db_uri and db_uri.startswith("postgres://"):
        db_uri = db_uri.replace("postgres://", "postgresql://", 1)
        
    app.config['SQLALCHEMY_DATABASE_URI'] = db_uri
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'secret_key_123')
    
    # 注册数据库
    db.init_app(app)
    
    # ⚠️ 关键修复：在这里注册 'from_json' 过滤器
    @app.template_filter('from_json')
    def from_json_filter(value):
        try:
            return json.loads(value)
        except:
            return {}

    # 注册蓝图
    from .web_routes import web_bp
    app.register_blueprint(web_bp)
    
    return app
