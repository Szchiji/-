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
    # 增加 threaded=True 确保并发处理
    app.run(host='0.0.0.0', port=port, use_reloader=False, threaded=True)

def start_bot_process():
    # 稍微多等一会儿，确保 Flask 彻底启动
    time.sleep(10)
    from app.modules.core.routes import run_bot
    print("🤖 正在启动机器人进程...", flush=True)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(run_bot())
    except Exception as e:
        print(f"❌ 机器人进程出错: {e}", flush=True)
    finally:
        loop.close()

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
    
    # 3. 启动机器人
    try:
        start_bot_process()
        print("🎉 系统已就绪，正在等待消息...", flush=True)
        # 死循环保持容器不退出
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        sys.exit(0)
