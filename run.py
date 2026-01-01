from app import create_app, db
import threading
import asyncio
import os
import sys

app = create_app()

def run_flask():
    port = int(os.getenv('PORT', 5000))
    # 关键：use_reloader=False 防止Flask重启导致机器人启动两次
    app.run(host='0.0.0.0', port=port, use_reloader=False)

def start_bot_loop():
    from app.bot_routes import run_bot
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    print("🤖 机器人正在启动...", flush=True)
    loop.run_until_complete(run_bot())

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    
    # 1. 启动网页 (子线程)
    t = threading.Thread(target=run_flask, daemon=True)
    t.start()
    
    # 2. 启动机器人 (主线程)
    try:
        start_bot_loop()
    except KeyboardInterrupt:
        print("停止运行...")
        sys.exit(0)
