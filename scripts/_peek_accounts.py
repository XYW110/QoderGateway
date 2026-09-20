# -*- coding: utf-8 -*-
"""_peek_accounts.py — 只读查看入库账号（不打印任何密钥明文，只显示长度/短摘要）。"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

DB = Path.home() / ".qoder" / "qoder2api.db"
print("DB_PATH:", DB)
print("exists:", DB.exists(), "| size:", DB.stat().st_size if DB.exists() else 0, "bytes")
for extra in (".db-wal", ".db-shm"):
    p = Path(str(DB) + extra.replace(".db", "", 1) if extra.startswith(".db-shm") else str(DB) + extra[3:])
    q = DB.parent / (DB.name + extra[3:])
    print("  sidecar:", q.name, q.exists(), q.stat().st_size if q.exists() else 0)

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
tables = [r[0] for r in conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
print("\ntables:", tables)

print("\naccounts columns:", [d[1] for d in conn.execute("PRAGMA table_info(accounts)")])
rows = conn.execute(
    "SELECT uid, name, email, length(password) AS pw_len, user_type, plan, user_tag, enabled,"
    " last_status, quota, length(security_oauth_token) AS tok_len,"
    " length(refresh_token) AS rt_len, machine_id, token_expires_at"
    " FROM accounts ORDER BY rowid").fetchall()
print(f"\naccounts rows: {len(rows)}")
for r in rows:
    print(f"  uid={r['uid']} email={r['email']} pw_len={r['pw_len']}"
          f" name={r['name']!r} plan={r['plan']} enabled={r['enabled']}"
          f" status={r['last_status']} token_len={r['tok_len']} rt_len={r['rt_len']}"
          f" exp={r['token_expires_at']}")

print("\nsettings keys:", [r[0] for r in conn.execute("SELECT key FROM settings")])
act = conn.execute("SELECT value FROM settings WHERE key='active_uid'").fetchone()
print("active_uid:", act[0] if act else None)
print("\nallowed_keys rows:", conn.execute("SELECT COUNT(*) FROM allowed_keys").fetchone()[0])
conn.close()
