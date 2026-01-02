from app import create_app, db
import threading
import asyncio
import os
import sys
import time
from sqlalchemy import text

app = create_app()

def fix_database_schema(app):
    """
    后台线程：慢慢修复数据库，绝不卡主进程
    """
    # 延迟 3 秒执行，给主进程一点喘息时间
    time.sleep(3)
    with app.app_context():
        try:
            # 1. 确保表存在
            db.create_all()
            
            # 2. 尝试补全字段 (使用独立连接)
            with db.engine.connect() as conn:
                # 修复 bot_groups
                try: 
                    conn.execute(text("ALTER TABLE bot_groups ADD COLUMN last_query_msg_id INTEGER"))
                except: pass
                
                # 修复 group_users
                try: 
                    conn.execute(text("ALTER TABLE group_users ADD COLUMN expiration_date TIMESTAMP"))
                except: pass
                
                try: 
                    conn.execute(text("ALTER TABLE group_users ADD COLUMN is_banned BOOLEAN DEFAULT FALSE"))
                except: pass
                
                conn.commit()
            print("✅ [后台] 数据库结构检查完成", flush=True)
        except Exception as e:
            print(f"⚠️ [后台] 数据库检查跳过: {e}", flush=True)

def run_flask():
    """
    启动 Web 服务 (Railway 健康检查必需)
    """
    port = int(os.getenv('PORT', 5000))
    # use_reloader=False 防止在容器中启动两次
    app.run(host='0.0.0.0', port=port, use_reloader=False)

def start_bot_loop():
    """
    启动机器人
    """
    # 延迟 5 秒启动机器人，优先让 Flask 跑起来
    time.sleep(5)
    from app.modules.core.routes import run_bot
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    print("🤖 机器人正在启动...", flush=True)
    loop.run_until_complete(run_bot())

if __name__ == '__main__':
    print("🚀 系统启动中...", flush=True)

    # 1. 最优先：启动 Flask (为了通过 Railway 健康检查)
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    # 2. 次优先：启动数据库修复 (后台默默跑)
    db_thread = threading.Thread(target=fix_database_schema, args=(app,), daemon=True)
    db_thread.start()
    
    # 3. 最后：启动机器人 (主线程阻塞)
    try:
        start_bot_loop()
    except KeyboardInterrupt:
        sys.exit(0)
