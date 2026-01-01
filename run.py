from app import create_app, db
import threading
import asyncio
import os
import sys

app = create_app()

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
    with app.app_context():
        # ⚠️⚠️⚠️ 强制重置数据库结构 (解决 column does not exist 报错)
        # 部署成功运行一次后，建议把这行注释掉，否则每次重启都会丢数据
        db.drop_all() 
        db.create_all()
        print("✅ 数据库已重置，新字段已生效", flush=True)
    
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    try:
        start_bot_loop()
    except KeyboardInterrupt:
        sys.exit(0)
