import os

class Config:
    # 替换为你自己的 Token
    BOT_TOKEN = os.getenv('BOT_TOKEN', 'YOUR_BOT_TOKEN_HERE')
    # 替换为你的数据库地址
    SQLALCHEMY_DATABASE_URI = 'sqlite:///bot.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = os.getenv('SECRET_KEY', 'your-secret-key-for-flask')
    # 管理员 ID (Telegram ID)
    ADMIN_ID = int(os.getenv('ADMIN_ID', '123456789'))
