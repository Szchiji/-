from app import create_app, db
import threading
import asyncio
import os
import sys

# 创建应用
app = create_app()

def run_flask():
    port = int(os.getenv('PORT', 5000))
    # use_reloader=False 避免二次启动导致机器人冲突
    app.run(host='0.0.0.0', port=port, use_reloader=False)

def start_bot_loop():
    # 动态导入，避免循环依赖
    from app.modules.core.routes import run_bot
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    print("🤖 机器人正在启动...", flush=True)
    loop.run_until_complete(run_bot())

if __name__ == '__main__':
    # 1. 初始化数据库
    with app.app_context():
        db.create_all()
    
    # 2. 启动网页 (守护线程)
    t = threading.Thread(target=run_flask, daemon=True)
    t.start()
    
    # 3. 启动机器人 (主线程阻塞)
    try:
        start_bot_loop()
    except KeyboardInterrupt:
        print("停止运行...")
        sys.exit(0)
