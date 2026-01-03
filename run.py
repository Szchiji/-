from app import create_app, db
import threading
import asyncio
import os
import sys
import time
from sqlalchemy import text

app = create_app()

def fix_database_schema(app):
    time.sleep(3)
    with app.app_context():
        try:
            db.create_all()
            with db.engine.connect() as conn:
                try: conn.execute(text("ALTER TABLE bot_groups ADD COLUMN last_query_msg_id INTEGER"))
                except: pass
                try: conn.execute(text("ALTER TABLE group_users ADD COLUMN expiration_date TIMESTAMP"))
                except: pass
                try: conn.execute(text("ALTER TABLE group_users ADD COLUMN is_banned BOOLEAN DEFAULT FALSE"))
                except: pass
                conn.commit()
            print("✅ [后台] 数据库结构检查完成", flush=True)
        except Exception as e:
            print(f"⚠️ [后台] 数据库检查跳过: {e}", flush=True)

def run_flask():
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, use_reloader=False, threaded=True)

def start_bot_process_forever(flask_app):
    """
    启动一个永不退出的事件循环，供 Webhook 使用
    """
    time.sleep(3)
    from app.modules.core.routes import run_bot
    
    print("🤖 启动机器人后台循环...", flush=True)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # 1. 初始化 (传入 Flask App 实例)
    loop.run_until_complete(run_bot(flask_app))
    
    # 2. ⚡ 核心：让 Loop 永远跑下去，活着等待 Flask 的投喂
    print("✅ 机器人循环已启动，正在监听 Webhook 任务...", flush=True)
    loop.run_forever()

if __name__ == '__main__':
    domain = os.getenv('RAILWAY_PUBLIC_DOMAIN')
    mode = "Webhook" if domain else "Polling"
    print(f"🚀 系统启动中 ({mode} 模式)...", flush=True)

    # 1. 启动 Web (Flask)
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    # 2. 数据库修复
    db_thread = threading.Thread(target=fix_database_schema, args=(app,), daemon=True)
    db_thread.start()
    
    # 3. 启动机器人 (在独立线程中跑 loop_forever)
    # ⚡️ 修复点：将 app 传入机器人线程
    bot_thread = threading.Thread(target=start_bot_process_forever, args=(app,), daemon=True)
    bot_thread.start()
    
    # 4. 主线程死循环保活
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        sys.exit(0)