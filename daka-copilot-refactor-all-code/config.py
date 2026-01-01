import os
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv('TOKEN')
DB_URI = os.getenv('DB_URI', 'sqlite:///bot.db')
ADMIN_ID = int(os.getenv('ADMIN_ID', '0'))
SECRET_KEY = os.getenv('SECRET_KEY')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'password')
PANEL_URL = os.getenv('PANEL_URL', 'http://localhost:5000')
MAIN_CHAT_ID = int(os.getenv('MAIN_CHAT_ID', '0'))
JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY')
SIDEBAR_MENU = [
    {'name': '首页', 'url': '/'},
    {'name': '打卡配置', 'url': '/checkin_config'},
    {'name': '认证配置', 'url': '/auth_config'},
    {'name': '自动回复', 'url': '/auto_reply'},
    {'name': '定时广播', 'url': '/scheduled'},
    {'name': '强制订阅', 'url': '/force_subscribe'},
    {'name': '积分配置', 'url': '/points_config'},
]
