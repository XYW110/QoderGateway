# -*- coding: utf-8 -*-
"""test_export_roundtrip.py — 隔离验证 导出 → 批量导入 的回环（不碰真库）。

覆盖三点：
  1. export_accounts() 字段完整（email/password/token/refresh_token/machine_id/user_id）
  2. 导出的数组原样喂给 batch_import_accounts() 后，关键字段逐一保真
  3. 记录缺 email/password 时，导入不会把库里已有值清空（修过的整行覆盖隐患）
"""
from __future__ import annotations

import json
import shutil
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

fails: list[str] = []


def check(cond: bool, label: str) -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
    if not cond:
        fails.append(label)


def fetch(uid: str) -> dict | None:
    conn = sqlite3.connect(db.DB_PATH)
    conn.row_factory = sqlite3.Row
    r = conn.execute("SELECT * FROM accounts WHERE uid = ?", (uid,)).fetchone()
    conn.close()
    return dict(r) if r else None


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="qoder_rt_"))
    db.DB_PATH = tmp / "src.db"
    db.init_db()
    from qoder2api.accounts import batch_import_accounts, export_accounts  # noqa: E402
    from qoder2api.registrar import _save_account  # noqa: E402

    # --- 1) 造一条带 email/password 的账号 ---
    uid = _save_account("rt", {"email": "rt+one@gmail.com", "password": "Pw!12345678",
                               "name": "RT One"},
                        {"user_id": "uid-rt-1", "token": "dt-rt-token",
                         "refresh_token": "drt-rt-refresh", "expires_at": "2026-12-31T00:00:00Z"})
    src = fetch(uid)
    print("1) 源记录:", {k: src[k] for k in ("uid", "email", "name", "token_expires_at")})

    records = export_accounts()
    print("   导出条数:", len(records), "| 字段:", sorted(records[0].keys()))
    rec = records[0]
    check(rec["user_id"] == uid, "user_id 对应")
    check(rec["email"] == "rt+one@gmail.com", "email 导出")
    check(rec["password"] == "Pw!12345678", "password 导出")
    check(rec["token"] == src["security_oauth_token"], "token 导出")
    check(rec["refresh_token"] == src["refresh_token"], "refresh_token 导出")
    check(rec["machine_id"] == src["machine_id"], "machine_id 导出")
    check(rec["expires_at"] == src["token_expires_at"], "expires_at 导出")

    # --- 2) 换一个新库，把导出结果原样导入 ---
    db.DB_PATH = tmp / "dst.db"
    db.init_db()
    res = batch_import_accounts(records)
    print("2) 导入结果:", res)
    got = fetch(uid)
    check(res["imported"] == 1, "导入 1 条")
    check(got is not None, "目标库存在该 uid")
    if got:
        check(got["email"] == "rt+one@gmail.com", "email 保真")
        check(got["password"] == "Pw!12345678", "password 保真")
        check(got["security_oauth_token"] == src["security_oauth_token"], "token 保真")
        check(got["refresh_token"] == src["refresh_token"], "refresh_token 保真")
        check(got["machine_id"] == src["machine_id"], "machine_id 保真")
        check(got["token_expires_at"] == src["token_expires_at"], "expires_at 保真")

    # --- 3) 缺 email/password 的记录不得清空已有值 ---
    batch_import_accounts([{"user_id": uid, "token": "dt-new-token"}])
    got2 = fetch(uid)
    print("3) 二次导入(仅 user_id+token):", {k: got2[k] for k in ("email", "password", "security_oauth_token")})
    check(got2["email"] == "rt+one@gmail.com", "缺 email 时保留旧 email")
    check(got2["password"] == "Pw!12345678", "缺 password 时保留旧 password")
    check(got2["security_oauth_token"] == "dt-new-token", "token 已更新")

    # --- 4) --no-secrets 导出不得含敏感字段 ---
    pub = export_accounts(include_secrets=False)
    check(all("password" not in r and "token" not in r and "refresh_token" not in r
              for r in pub), "include_secrets=False 剔除敏感字段")
    check(all(r.get("email") for r in pub), "include_secrets=False 仍保留 email")

    shutil.rmtree(tmp, ignore_errors=True)
    print("\nRESULT:", "PASS" if not fails else f"FAIL ({len(fails)}): {fails}")
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(main())
