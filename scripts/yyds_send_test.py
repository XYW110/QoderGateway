#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
yyds_send_test.py — 独立测试 YYDS 临时邮箱的「收信」链路是否可用（不依赖 qoder）。

流程：
  1. 用 YYDS_API_KEY 通过 API 创建临时邮箱地址
  2. 解析该地址域名的 MX 记录（PowerShell Resolve-DnsName）
  3. 直接经 SMTP 25 向 MX 投递一封含 6 位验证码的测试邮件
     （HELO / MAIL FROM / RCPT TO / DATA，RFC 5321 合规）
  4. 轮询 /v1/messages/next 看能否取回邮件并找到验证码
  5. 结论：
     PASS  -> YYDS 收件链路 OK，问题出在 qoder 侧（域名被过滤/根本没发信）
     FAIL  -> YYDS 侧收件或取信链路有问题

用法：
  .venv\\Scripts\\python.exe scripts/yyds_send_test.py [--timeout 90]
"""
from __future__ import annotations

import argparse
import os
import re
import smtplib
import subprocess
import sys
import time
import uuid
from email.mime.text import MIMEText
from pathlib import Path

if sys.platform == "win32":  # Windows 控制台默认 GBK，强制 UTF-8 输出
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

DEFAULT_API = "https://vip.215.im/v1"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CODE_RE = re.compile(r"(?<!\d)(\d{6})(?!\d)")


def _api_base() -> str:
    base = (os.getenv("YYDS_API_BASE") or "").strip()
    if base:
        return base.rstrip("/")
    p = PROJECT_ROOT / ".env"
    if p.exists():
        for raw in p.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line.startswith("YYDS_API_BASE="):
                v = line.split("=", 1)[1].strip().strip('"').strip("'")
                if v:
                    return v.rstrip("/")
    return DEFAULT_API


def _api_key() -> str:
    k = (os.getenv("YYDS_API_KEY") or "").strip()
    if k:
        return k
    p = PROJECT_ROOT / ".env"
    if p.exists():
        for raw in p.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line.startswith("YYDS_API_KEY="):
                v = line.split("=", 1)[1].strip().strip('"').strip("'")
                if v:
                    return v
    raise SystemExit("ERROR: YYDS_API_KEY 未配置（项目根 .env 或环境变量）")


def create_mailbox() -> str:
    import httpx
    local = "qodertest" + uuid.uuid4().hex[:8]
    r = httpx.post(
        f"{_api_base()}/accounts",
        headers={"X-API-Key": _api_key(), "Content-Type": "application/json"},
        json={"localPart": local},
        timeout=20,
    )
    r.raise_for_status()
    data = r.json()["data"]
    addr: str = data["address"]
    print(f"[+] 创建测试邮箱 OK -> {addr}  (expires {data.get('expiresAt')})")
    return addr


def mx_of(domain: str) -> list[str]:
    """用 PowerShell Resolve-DnsName 查 MX，返回 NameExchange 列表（失败则空）。"""
    try:
        out = subprocess.run(
            [
                "powershell", "-NoProfile", "-Command",
                f"Resolve-DnsName -Name {domain} -Type MX | "
                f"Where-Object {{ $_.Type -eq 'MX' }} | Select-Object -ExpandProperty NameExchange",
            ],
            capture_output=True, text=True, timeout=25,
        )
        lines = [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]
        return lines
    except Exception as e:
        print(f"[!] MX 查询失败: {e}")
        return []


def send_via_smtp(mx_host: str, to_addr: str, code: str, from_addr: str = "gateway-test@example.com") -> bool:
    """直连 MX 25 投递一封含验证码的测试邮件，返回是否被接受(250)。"""
    msg = MIMEText(
        "Independent mailbox self-test (yyds_send_test.py)\r\n\r\n"
        f"Your verification code is {code}.\r\n\r\n"
        "This message was injected directly over SMTP to validate the YYDS receive path.",
        "plain", "utf-8",
    )
    msg["From"] = format_addr = from_addr
    msg["To"] = to_addr
    msg["Subject"] = "YYDS receive-path self test"
    try:
        host = mx_host.rstrip(".")
        with smtplib.SMTP(host=host, port=25, timeout=30, local_hostname="localhost") as s:
            c, resp = s.ehlo()  # Inbucket 要求先 EHLO/HELO，否则 MAIL FROM 报 503
            print(f"    EHLO      -> {c} {resp}")
            if c != 250:
                c, resp = s.helo()
                print(f"    HELO      -> {c} {resp}")
                if c != 250:
                    return False
            c, resp = s.mail(from_addr)
            print(f"    MAIL FROM -> {c} {resp}")
            if c != 250:
                return False
            c, resp = s.rcpt(to_addr)
            print(f"    RCPT TO   -> {c} {resp}")
            if c != 250:
                return False
            c, resp = s.data(msg.as_bytes())
            print(f"    DATA      -> {c} {resp}")
            return c == 250
    except Exception as e:
        print(f"    SMTP 投递异常: {type(e).__name__}: {e}")
        return False


def poll_mailbox(address: str, expect: str, timeout: float) -> tuple[bool, str]:
    """轮询 /v1/messages/next，判断是否收到含 expect 的邮件。返回 (bool, 详情)。"""
    import httpx
    key = _api_key()
    deadline = time.time() + timeout
    last = "轮询尚未开始"
    while time.time() < deadline:
        try:
            r = httpx.get(
                f"{_api_base()}/messages/next",
                params={"address": address, "wait": 20},
                headers={"X-API-Key": key},
                timeout=45,
            )
            if r.status_code == 200:
                m = r.json()["data"]["message"]
                txt = m.get("text") or ""
                if expect and expect in txt:
                    return True, f"收到邮件 subject={m.get('subject')!r}, 内含预期 {expect}"
                if CODE_RE.search(txt):
                    return True, f"收到邮件 subject={m.get('subject')!r}, 内含验证码 {CODE_RE.search(txt).group(1)}"
                last = f"200 但无关邮件 subject={m.get('subject')!r} text={txt[:80]!r}"
            elif r.status_code == 204:
                last = "204 no message"
            else:
                last = f"unexpected {r.status_code}: {r.text[:120]}"
        except Exception as e:
            last = f"poll {type(e).__name__}: {e}"
        print(f"    ... {last}")
        time.sleep(2)
    return False, f"timeout {timeout:.0f}s, last={last}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=float, default=90.0, help="取信轮询秒数")
    args = ap.parse_args()

    print(f"API 基址: {_api_base()}")
    addr = create_mailbox()
    domain = addr.rsplit("@", 1)[1]

    mxs = mx_of(domain)
    print(f"[*] {domain} 的 MX: {mxs if mxs else '(无/查询失败)'}")
    if not mxs:
        print("[!] 无 MX 记录：外部发信方将无法投递，YYDS 该域可能是下线/未配置状态。")
    targets = mxs or [domain]

    ok_smtp = False
    for mx in targets:
        print(f"[*] 尝试 SMTP 直投到 MX {mx} ...")
        if send_via_smtp(mx, addr, "482913"):
            ok_smtp = True
            break
    print(f"\n== SMTP 投递: {'accepted' if ok_smtp else 'REJECTED / 不可达'} ==")

    recv, detail = poll_mailbox(addr, "482913", args.timeout)
    print(f"== 取信轮询: {'收到验证码' if recv else '未收到'} ({detail}) ==")

    if ok_smtp and recv:
        print("结论: PASS — YYDS 邮箱收件链路正常（直接投递可收到）。")
        print("      因此 qoder 验证码收不到，问题在 qoder 侧：域名被过滤/限制，或邮件根本没被发送。")
        return 0
    if not ok_smtp and not recv:
        print("结论: FAIL — SMTP 投递都不可达/被拒，YYDS 邮箱侧链路很可能有问题。")
        return 1
    if ok_smtp and not recv:
        print("结论: PARTIAL — SMTP 接受但轮询超时，可能是取信接口问题或投递延迟过大。")
        return 2
    print("结论: PARTIAL — SMTP 未成功但邮箱中已存在消息（异常）。")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())