from app import create_app, db
import threading
import asyncio
import os
import sys

# 创建 Flask 应用实例
app = create_app()

def run_flask():
    port = int(os.getenv('PORT', 5000))
    # ⚠️ 关键：use_reloader=False 绝对不能改
    app.run(host='0.0.0.0', port=port, use_reloader=False)

def start_bot_loop():
    from app.bot_routes import run_bot
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    print("🤖 机器人正在启动...", flush=True)
    loop.run_until_complete(run_bot())

if __name__ == '__main__':
    # 数据库初始化
    with app.app_context():
        db.create_all()
    
    # 启动 Flask (网页后台)
    # daemon=True 表示主程序退出时它也退出
    t = threading.Thread(target=run_flask, daemon=True)
    t.start()
    
    # 启动 机器人 (主线程)
    try:
        start_bot_loop()
    except KeyboardInterrupt:
        print("停止运行...")
        sys.exit(0)
    except Exception as e:
        print(f"❌ 发生错误: {e}")
