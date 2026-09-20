import sqlite3
from pathlib import Path

conn = sqlite3.connect(Path.home() / ".qoder" / "qoder2api.db")
for row in conn.execute("SELECT key, substr(value,1,16) FROM settings"):
    print(row)
