# -*- coding: utf-8 -*-
"""export_accounts.py — 把本地账号池导出为注册机 accounts.json（含邮箱/密码/token）。

不依赖网关服务，直接读写本地 SQLite。

用法：
  python scripts/export_accounts.py                    # 写项目根 accounts.json
  python scripts/export_accounts.py --out D:\\tmp\\a.json
  python scripts/export_accounts.py --no-secrets       # 剔除 password/token/refresh_token
  python scripts/export_accounts.py --stdout           # 打印到标准输出（不落盘）

⚠️ 默认包含明文邮箱/密码/token，注意保管；accounts.json 已被 .gitignore 忽略。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(r"D:\Work\Project\TestProject\QoderGateway")
sys.path.insert(0, str(ROOT / "src"))

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from qoder2api.accounts import export_accounts  # noqa: E402
from qoder2api.database import DB_PATH  # noqa: E402


def main() -> int:
    args = sys.argv[1:]
    to_stdout = "--stdout" in args
    no_secrets = "--no-secrets" in args
    out = None
    for i, a in enumerate(args):
        if a == "--out" and i + 1 < len(args):
            out = Path(args[i + 1])

    records = export_accounts(include_secrets=not no_secrets)
    body = json.dumps(records, ensure_ascii=False, indent=2)

    if to_stdout:
        print(body)
        return 0

    target = out or (ROOT / "accounts.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    print(f"[ok] 已导出 {len(records)} 个账号 → {target}  ({len(body)} bytes)")
    print(f"     来源库: {DB_PATH}")
    if not no_secrets:
        with_mail = sum(1 for r in records if r.get("email"))
        with_pw = sum(1 for r in records if r.get("password"))
        without_pw = [r.get("user_id") for r in records if r.get("email") and not r.get("password")]
        print(f"     含 email {with_mail}/{len(records)}，含 password {with_pw}/{len(records)}")
        if without_pw:
            print(f"     ⚠️ {len(without_pw)} 个账号缺密码（历史注册未落盘，无法恢复）：")
            for u in without_pw:
                print("       ", u)
        print("     注意：文件含明文凭据，请勿提交或外发")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
