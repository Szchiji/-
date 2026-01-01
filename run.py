from app import create_app, db
import threading
import asyncio
import os

app = create_app()

def run_flask():
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, use_reloader=False)

def start_bot_loop():
    # 在这里导入以避免循环引用
    from app.bot_routes import run_bot
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(run_bot())

if __name__ == '__main__':
    with app.app_context():
        # ⚠️ 如果报错，取消注释下面一行重置数据库
        # db.drop_all() 
        db.create_all()
    
    # 启动 Flask 网页
    t = threading.Thread(target=run_flask, daemon=True)
    t.start()
    
    # 启动 机器人
    try:
        start_bot_loop()
    except KeyboardInterrupt:
        pass
