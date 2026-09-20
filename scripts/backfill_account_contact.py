# -*- coding: utf-8 -*-
"""backfill_account_contact.py — 把历史账号的邮箱回填进 accounts.email。

密码无法回填：注册密码由 _random_password() 随机生成且从未落盘（日志不含、无导出文件、
内存任务结果重启即丢），历史行的 password 只能留空。

邮箱来源（按优先级）：
  A. .snow/logs/*.log    `account saved to DB: <uid> (<email>)`  → uid→email
  B. .snow/logs/*.log    `[<task_id>] [mail] created <email>`   → task_id→email
                         + `[<task_id>] ... account saved to DB: <uid>` → task_id→uid
  C. logs/mail/*.txt     meta 里的 `task_id=` / `address=`      → task_id→email（兜底）

用法：
  python scripts/backfill_account_contact.py            # 干跑，只打印计划
  python scripts/backfill_account_contact.py --apply    # 实际写库
  python scripts/backfill_account_contact.py --apply --set <uid>=<email>   # 手工补一条
"""
from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(r"D:\Work\Project\TestProject\QoderGateway")
sys.path.insert(0, str(ROOT / "src"))

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from qoder2api.database import DB_PATH, init_db  # noqa: E402

RE_SAVED = re.compile(r"account saved to DB:\s*(?P<uid>[0-9a-fA-F-]{8,})\s*\((?P<email>[^)]+)\)")
RE_SAVED_TID = re.compile(r"\[(?P<tid>[^\]]+)\][^\[\]]*account saved to DB:\s*(?P<uid>[0-9a-fA-F-]{8,})")
RE_MAIL_TID = re.compile(r"\[(?P<tid>[^\]]+)\]\s*\[mail\] created\s+(?P<email>\S+)")
RE_VERDICT = re.compile(r"^\[(?P<tid>[^\]]+)\]\s*\[reg\]\s*name=.*?mail=(?P<email>\S+)")


def scan_logs() -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """返回 (uid→email, tid→email, tid→uid)。"""
    uid2mail: dict[str, str] = {}
    tid2mail: dict[str, str] = {}
    tid2uid: dict[str, str] = {}
    logdir = ROOT / ".snow" / "logs"
    files = sorted(logdir.glob("*.log")) if logdir.exists() else []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for line in text.splitlines():
            m = RE_SAVED.search(line)
            if m:
                uid2mail.setdefault(m.group("uid"), m.group("email"))
            m = RE_SAVED_TID.search(line)
            if m:
                tid2uid.setdefault(m.group("tid"), m.group("uid"))
            for rx in (RE_MAIL_TID, RE_VERDICT):
                m = rx.search(line)
                if m:
                    tid2mail.setdefault(m.group("tid"), m.group("email"))
    print(f"[scan] 日志文件 {len(files)} 个 → uid→email {len(uid2mail)} 条, "
          f"tid→email {len(tid2mail)} 条, tid→uid {len(tid2uid)} 条")
    return uid2mail, tid2mail, tid2uid


def scan_mail_dumps() -> dict[str, str]:
    """logs/mail/*.txt 的 meta：task_id / address。"""
    tid2mail: dict[str, str] = {}
    d = ROOT / "logs" / "mail"
    files = list(d.glob("*.txt")) if d.exists() else []
    for f in files:
        try:
            head = f.read_text(encoding="utf-8", errors="replace")[:1200]
        except Exception:
            continue
        tid = addr = None
        for line in head.splitlines():
            if line.startswith("task_id="):
                tid = line.split("=", 1)[1].strip()
            elif line.startswith("address="):
                addr = line.split("=", 1)[1].strip()
        if tid and addr:
            tid2mail.setdefault(tid, addr)
    print(f"[scan] 邮件落盘 {len(files)} 个 → tid→email {len(tid2mail)} 条")
    return tid2mail


def main() -> int:
    init_db()
    apply = "--apply" in sys.argv
    manual: dict[str, str] = {}
    for i, a in enumerate(sys.argv):
        if a == "--set" and i + 1 < len(sys.argv) and "=" in sys.argv[i + 1]:
            uid, _, mail = sys.argv[i + 1].partition("=")
            manual[uid.strip()] = mail.strip()

    uid2mail, tid2mail, tid2uid = scan_logs()
    mail_tid2mail = scan_mail_dumps()
    # 兜底：邮件落盘的 tid→email 通过 tid→uid 折成 uid→email
    for tid, mail in mail_tid2mail.items():
        uid = tid2uid.get(tid)
        if uid:
            uid2mail.setdefault(uid, mail)
    uid2mail.update(manual)
    print(f"[plan] 可回填 uid→email 共 {len(uid2mail)} 条（含手工 {len(manual)} 条）")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT uid, name, email FROM accounts ORDER BY rowid").fetchall()
    todo: list[tuple[str, str]] = []
    for r in rows:
        if r["email"]:
            continue
        mail = uid2mail.get(r["uid"])
        if mail:
            todo.append((r["uid"], mail))
            tag = "OK  "
        else:
            tag = "MISS"
        print(f"  {tag} {r['uid']} name={r['name']!r} email={mail or '<未知>'}")
    if apply and todo:
        for uid, mail in todo:
            conn.execute("UPDATE accounts SET email = ? WHERE uid = ? AND (email IS NULL OR email = '')",
                         (mail, uid))
        conn.commit()
        print(f"[apply] 已回填 {len(todo)} 行 email")
    elif not apply:
        print(f"[dry-run] 待回填 {len(todo)} 行（加 --apply 才写库）")
    miss = [r["uid"] for r in rows if not r["email"] and not uid2mail.get(r["uid"])]
    if miss:
        print(f"[warn] 仍无法确定邮箱 {len(miss)} 行，可用 --set <uid>=<email> 手工补：")
        for u in miss:
            print("   ", u)
    print("[note] password 无法回填：注册密码随机生成且从未落盘（历史行只能留空）")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
