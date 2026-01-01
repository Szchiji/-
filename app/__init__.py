from flask import Flask
from flask_sqlalchemy import SQLAlchemy
import os

db = SQLAlchemy()

def create_app():
    app = Flask(__name__)
    
    # 配置
    db_uri = os.getenv('DATABASE_URL', 'sqlite:///bot.db')
    if db_uri.startswith("postgres://"):
        db_uri = db_uri.replace("postgres://", "postgresql://", 1)
        
    app.config['SQLALCHEMY_DATABASE_URI'] = db_uri
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'secret')
    
    db.init_app(app)
    
    # 注册蓝图/路由
    from .web_routes import web_bp
    app.register_blueprint(web_bp)
    
    return app
