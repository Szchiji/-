from app import create_app, db
import threading
import asyncio
import os
import sys
import time
from sqlalchemy import text

app = create_app()

def fix_database_schema(app):
    """后台修复数据库"""
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
    app.run(host='0.0.0.0', port=port, use_reloader=False)

def setup_webhook_once():
    """配置 Webhook (只运行一次)"""
    time.sleep(5) # 等 Flask 跑起来
    
    domain = os.getenv('RAILWAY_PUBLIC_DOMAIN')
    if not domain:
        print("⚠️ 未检测到 RAILWAY_PUBLIC_DOMAIN，跳过 Webhook 设置", flush=True)
        return

    from app.modules.core.routes import init_webhook_bot
    
    print(f"🌍 检测到域名: {domain}", flush=True)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(init_webhook_bot(domain))
    finally:
        loop.close()

if __name__ == '__main__':
    print("🚀 系统启动中 (Webhook 模式)...", flush=True)

    # 1. 启动 Web 服务
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    # 2. 数据库修复
    db_thread = threading.Thread(target=fix_database_schema, args=(app,), daemon=True)
    db_thread.start()
    
    # 3. 设置 Webhook (运行一次即退出，不需要死循环)
    setup_webhook_once()
    
    # 4. 保持主线程存活
    try:
        while True: time.sleep(1)
    except KeyboardInterrupt:
        sys.exit(0)
