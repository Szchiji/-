from app import create_app, db
import threading
import asyncio
import os
import sys
from sqlalchemy import text

app = create_app()

def fix_database_schema(app):
    """
    自动检测并修复缺失的数据库列
    """
    with app.app_context():
        db.create_all()
        
        # 修复 BotGroup 表
        try:
            with db.engine.connect() as conn:
                conn.execute(text("SELECT last_query_msg_id FROM bot_groups LIMIT 1"))
        except:
            print("🔧 补全 bot_groups.last_query_msg_id", flush=True)
            with db.engine.connect() as conn:
                conn.execute(text("ALTER TABLE bot_groups ADD COLUMN last_query_msg_id INTEGER"))
                conn.commit()

        # 修复 GroupUser 表 (新增有效期和禁言字段)
        try:
            with db.engine.connect() as conn:
                conn.execute(text("SELECT expiration_date FROM group_users LIMIT 1"))
        except:
            print("🔧 补全 group_users.expiration_date", flush=True)
            with db.engine.connect() as conn:
                conn.execute(text("ALTER TABLE group_users ADD COLUMN expiration_date TIMESTAMP"))
                conn.commit()

        try:
            with db.engine.connect() as conn:
                conn.execute(text("SELECT is_banned FROM group_users LIMIT 1"))
        except:
            print("🔧 补全 group_users.is_banned", flush=True)
            with db.engine.connect() as conn:
                conn.execute(text("ALTER TABLE group_users ADD COLUMN is_banned BOOLEAN DEFAULT FALSE"))
                conn.commit()

def run_flask():
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, use_reloader=False)

def start_bot_loop():
    from app.modules.core.routes import run_bot
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    print("🤖 机器人正在启动...", flush=True)
    loop.run_until_complete(run_bot())

if __name__ == '__main__':
    fix_database_schema(app)
    print("✅ 数据库检查完成", flush=True)
    
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    try:
        start_bot_loop()
    except KeyboardInterrupt:
        sys.exit(0)
