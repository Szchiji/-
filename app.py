from app import create_app, db
import threading
import asyncio
import os

app = create_app()

def run_flask():
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, use_reloader=False)

def start_bot_loop():
    from app.bot_routes import run_bot
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(run_bot())

if __name__ == '__main__':
    with app.app_context():
        # ⚠️ 首次运行或表结构变更时取消注释下面一行
        # db.drop_all() 
        db.create_all()
    
    # 启动 Web
    t = threading.Thread(target=run_flask, daemon=True)
    t.start()
    
    # 启动 Bot
    try:
        start_bot_loop()
    except KeyboardInterrupt:
        pass
