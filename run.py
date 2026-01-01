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
        # ⚠️ 首次部署或数据库报错时，取消注释下面一行以重置数据库
        # db.drop_all()
        db.create_all()
    
    # 启动 Flask 网页后台 (子线程)
    t = threading.Thread(target=run_flask, daemon=True)
    t.start()
    
    # 启动 Bot (主线程)
    try:
        start_bot_loop()
    except KeyboardInterrupt:
        pass
