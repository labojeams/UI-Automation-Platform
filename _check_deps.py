"""检查数据库里步骤 description 实际存的字节内容"""
import sqlite3
import os

db = os.path.join("backend", "data", "platform.db")
conn = sqlite3.connect(db)
cur = conn.cursor()

# 找最近修改的、含 "新增接待" 的步骤
cur.execute("SELECT id, description FROM steps WHERE description LIKE '%新增接待%' ORDER BY id DESC LIMIT 5")
rows = cur.fetchall()
for sid, desc in rows:
    print(f"--- step id={sid} ---")
    print(f"repr: {desc!r}")
    print(f"len : {len(desc)}")
    # 列出每个非 ASCII 字符位置
    for i, ch in enumerate(desc):
        if ord(ch) > 127 or ch in '"\'':
            print(f"  [{i}] {ch!r} U+{ord(ch):04X}")
    print()

conn.close()