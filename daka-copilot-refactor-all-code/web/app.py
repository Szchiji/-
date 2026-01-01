from flask import Flask
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_jwt_extended import JWTManager
from dotenv import load_dotenv
from models import db
from web.routes import init_routes
import os

load_dotenv()
app = Flask(__name__)

# 获取数据库连接字符串，并兼容 postgres:// 格式
db_uri = os.getenv('DB_URI') or os.getenv('DATABASE_URL') or 'sqlite:///bot.db'
if db_uri.startswith("postgres://"):
    db_uri = db_uri.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_uri
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = os.getenv('SECRET_KEY', 'default_secret')
app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY', 'your_jwt_secret')
db.init_app(app)
migrate = Migrate(app, db)
jwt = JWTManager(app)

login_manager = LoginManager(app)
login_manager.login_view = 'login'

from models import AdminUser
@login_manager.user_loader
def load_user(user_id):
    return AdminUser.query.get(int(user_id))

init_routes(app)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        if not AdminUser.query.filter_by(username='admin').first():
            admin = AdminUser(username='admin')
            admin.set_password(os.getenv('ADMIN_PASSWORD', 'password'))
            db.session.add(admin)
            db.session.commit()
    app.run(debug=True, port=5000)