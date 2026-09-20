# -*- coding: utf-8 -*-
"""test_save_account_email.py — 隔离验证 _save_account 是否真的把 email/password 写库。

用临时 DB（不碰 ~/.qoder/qoder2api.db），构造与 register() 相同形状的 acct/cred，
写入后读回核对列映射。
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(r"D:\Work\Project\TestProject\QoderGateway")
sys.path.insert(0, str(ROOT / "src"))

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import qoder2api.database as db  # noqa: E402

tmpdir = Path(tempfile.mkdtemp(prefix="qoder_dbtest_"))
db.DB_PATH = tmpdir / "test.db"
db.init_db()
print("temp DB:", db.DB_PATH)

from qoder2api.registrar import _save_account  # noqa: E402

EMAIL = "selftest+abc@gmail.com"
PASSWORD = "Tt3st!Passw0rd"
uid = _save_account(
    "selftest",
    {"email": EMAIL, "password": PASSWORD, "name": "Selftest User"},
    {"user_id": "uid-selftest-1", "token": "dt-fake-token",
     "refresh_token": "drt-fake-refresh", "expires_at": "2026-12-31T00:00:00Z"},
)
print("saved uid:", uid)

conn = sqlite3.connect(db.DB_PATH)
conn.row_factory = sqlite3.Row
r = conn.execute("SELECT * FROM accounts WHERE uid = ?", (uid,)).fetchone()
got = dict(r)
print("row:", {k: got[k] for k in ("uid", "name", "email", "user_type", "plan",
                                   "enabled", "token_expires_at")})
print("email     匹配:", got.get("email") == EMAIL, repr(got.get("email")))
print("password  匹配:", got.get("password") == PASSWORD,
      "len=%s" % (len(got["password"]) if got.get("password") else None))
print("token/refresh 落库:", got.get("security_oauth_token"), "/", got.get("refresh_token"))
ok = got.get("email") == EMAIL and got.get("password") == PASSWORD
print("\nRESULT:", "PASS" if ok else "FAIL")
conn.close()
import shutil  # noqa: E402
shutil.rmtree(tmpdir, ignore_errors=True)
raise SystemExit(0 if ok else 1)
