import sqlite3
from pathlib import Path

conn = sqlite3.connect(Path.home() / ".qoder" / "qoder2api.db")
cur = conn.execute(
    "UPDATE accounts SET proxy_password = '' WHERE proxy_password IS NOT NULL AND proxy_password != ''"
)
conn.commit()
print("cleared rows:", cur.rowcount)
