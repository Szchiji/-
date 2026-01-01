from app import create_app, db
import threading
import asyncio
import os
import sys
from sqlalchemy import text

app = create_app()

def fix_database_schema(app):
    """
    自动检测并修复缺失的数据库列，避免删除数据。
    """
    with app.app_context():
        # 1. 确保表存在
        db.create_all()
        
        # 2. 检查 bot_groups 表是否缺少 last_query_msg_id
        try:
            with db.engine.connect() as conn:
                # 尝试查询该字段，如果报错说明不存在
                conn.execute(text("SELECT last_query_msg_id FROM bot_groups LIMIT 1"))
        except Exception:
            print("🔧 检测到缺少 'last_query_msg_id' 字段，正在自动修复...", flush=True)
            try:
                with db.engine.connect() as conn:
                    conn.execute(text("ALTER TABLE bot_groups ADD COLUMN last_query_msg_id INTEGER"))
                    conn.commit()
                print("✅ 数据库修复完成！数据已保留。", flush=True)
            except Exception as e:
                print(f"⚠️ 修复失败 (可能是权限问题，或已存在): {e}", flush=True)

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
    # 启动前先运行修复脚本
    fix_database_schema(app)
    
    print("✅ 数据库已就绪", flush=True)
    
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    try:
        start_bot_loop()
    except KeyboardInterrupt:
        sys.exit(0)
