# -*- coding: utf-8 -*-
"""统一邮箱后端：Emailnator（真实 @gmail.com）优先，YYDS 仅作降级。

qoder 拒收 YYDS 整条 MX（smtp.215.im），6 个 clean 域 0/6 OTP。
Emailnator plusGmail/dotGmail 生成正规 gmail 地址，绕开该封禁。

收码硬约束：
  - Emailnator 收件箱是共享的，必须按 since=发码时刻过滤
  - 必须命中 qoder 关键字才认码（否则会误抓他人验证码，如 600000）
  - 邮件不一定马上到，默认等 300s、间隔 4s
  - 每封候选信的完整内容落到 logs/mail/，方便事后对照
"""
from __future__ import annotations

import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

_CHANNEL_MAIL = Path(__file__).resolve().parent.parent.parent / "temp" / "channel_mail"
_MAIL_LOG_DIR = Path(__file__).resolve().parent.parent.parent / "logs" / "mail"

# qoder 验证码邮件特征（发件人 / 主题 / 正文任一命中即认）
_QODER_HINTS = (
    "qoder",
    "qoder.com",
    "noreply@qoder",
    "verify your email",
    "verification code",
    "one-time code",
    "一次性验证码",
    "验证码",
)

_CODE_RE = re.compile(r"(?<!\d)(\d{6})(?!\d)")


def _mail_backend() -> str:
    return (os.getenv("QODER_MAIL_BACKEND") or "emailnator").strip().lower()


def _import_emailnator():
    root = str(_CHANNEL_MAIL)
    if root not in sys.path:
        sys.path.insert(0, root)
    from email_api import generate_email  # type: ignore
    from emailnator_client import EmailnatorClient  # type: ignore

    return generate_email, EmailnatorClient


def _looks_like_qoder(from_: str, subject: str, body: str) -> bool:
    blob = " ".join((from_ or "", subject or "", body or "")).lower()
    return any(h in blob for h in _QODER_HINTS)


def _strip_html(html: str) -> str:
    if not html:
        return ""
    text = re.sub(r"(?is)<style.*?</style>", " ", html)
    text = re.sub(r"(?is)<script.*?</script>", " ", text)
    text = re.sub(r"(?i)style=\"[^\"]*\"", " ", text)
    text = re.sub(r"(?i)style='[^']*'", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&\w+;", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _extract_code(text: str) -> str | None:
    if not text:
        return None
    plain = _strip_html(text)
    m = re.search(
        r"(?i)(?:code|verification|verify|otp|验证码)\D{0,20}(\d{6})",
        plain,
    )
    if m:
        return m.group(1)
    # qoder 模板：正文里码单独成段（Verify ... Qoder. 282397 This code expires）
    m = re.search(r"(?i)qoder\D{0,8}(\d{6})\D{0,12}(?:this code|expires|分钟)", plain)
    if m:
        return m.group(1)
    found = _CODE_RE.findall(plain)
    return found[0] if len(found) == 1 else None


def _dump_mail(task_id: str | None, address: str, meta: dict, body: str, verdict: str) -> Path:
    """把完整邮件落到 logs/mail/，返回路径。"""
    _MAIL_LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_tid = (task_id or "notid").replace("/", "_")
    mid = (meta.get("id") or meta.get("messageID") or "nomid")
    safe_mid = re.sub(r"[^A-Za-z0-9._-]+", "_", str(mid))[:80]
    path = _MAIL_LOG_DIR / f"{stamp}_{safe_tid}_{verdict}_{safe_mid}.txt"
    lines = [
        f"task_id={task_id}",
        f"address={address}",
        f"verdict={verdict}",
        f"id={mid}",
        f"from={meta.get('from')}",
        f"subject={meta.get('subject')}",
        f"timestamp={meta.get('timestamp')}",
        f"time_ago={meta.get('time_ago')}",
        f"locked={meta.get('locked')}",
        "----- meta -----",
        repr({k: meta.get(k) for k in meta}),
        "----- body -----",
        body or "",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8", errors="replace")
    return path


def create_mailbox(
    *,
    task_id: str | None = None,
    log: Callable[[str | None, str], None],
    yyds_fallback,
) -> str:
    """建箱。默认 Emailnator @gmail.com；失败或 QODER_MAIL_BACKEND=yyds 时走 YYDS。"""
    backend = _mail_backend()
    if backend in ("yyds", "yydsmail"):
        log(task_id, "[mail] backend=yyds (forced)")
        return yyds_fallback()

    try:
        generate_email, _ = _import_emailnator()
        email, bk = generate_email(gmail_only=True)
        host = (email.rsplit("@", 1)[-1] if email and "@" in email else "").lower()
        if host not in ("gmail.com", "googlemail.com"):
            raise RuntimeError(f"emailnator 未给出 gmail 地址: {email}")
        log(task_id, f"[mail] created {email} (backend={bk})")
        return email
    except Exception as e:
        log(task_id, f"[mail] emailnator 失败，降级 YYDS: {type(e).__name__}: {e}")
        return yyds_fallback()


def wait_code(
    address: str,
    *,
    task_id: str | None = None,
    timeout: float = 300.0,
    since: float | None = None,
    log: Callable[[str | None, str], None],
    yyds_fallback,
    interval: float = 4.0,
) -> str:
    """收码。gmail 走 Emailnator（since + qoder 关键字）；其余走 YYDS。

    默认等 300s（邮件不一定马上到）。每封候选信完整内容写入 logs/mail/。
    """
    host = (address.rsplit("@", 1)[-1] if address and "@" in address else "").lower()
    if host not in ("gmail.com", "googlemail.com"):
        log(task_id, f"[mail] wait via yyds ({address})")
        return yyds_fallback()

    send_ts = since if since is not None else time.time()
    log(
        task_id,
        f"[mail] wait via emailnator since={int(send_ts)} timeout={int(timeout)}s interval={interval}s",
    )
    _, EmailnatorClient = _import_emailnator()
    c = EmailnatorClient()
    seen: set[str] = set()
    scanned = 0
    skipped = 0
    try:
        deadline = time.time() + timeout
        last_n = -1
        while time.time() < deadline:
            try:
                msgs = c.message_list(address) or []
            except Exception as e:
                log(task_id, f"[mail] message-list 错误: {type(e).__name__}: {e}")
                time.sleep(interval)
                continue
            if len(msgs) != last_n:
                remain = int(max(0, deadline - time.time()))
                log(task_id, f"[mail] inbox {len(msgs)} msgs, remain={remain}s")
                last_n = len(msgs)
            cands = []
            for m in msgs:
                mid = EmailnatorClient.msg_id(m)
                if not mid or m.get("locked"):
                    continue
                ts = None
                try:
                    if m.get("timestamp") is not None:
                        ts = float(m.get("timestamp"))
                except Exception:
                    ts = None
                if ts is not None and ts < (send_ts - 10.0):
                    continue
                cands.append((ts if ts is not None else 0.0, mid, m))
            cands.sort(key=lambda x: -x[0])
            for _ts, mid, m in cands:
                if mid in seen:
                    continue
                seen.add(mid)
                scanned += 1
                frm = m.get("from") or ""
                subj = m.get("subject") or ""
                try:
                    body = c.get_message(address, mid) or ""
                except Exception as e:
                    body = f"<get_message failed: {type(e).__name__}: {e}>"
                blob = f"{frm}\n{subj}\n{body}"
                is_qoder = _looks_like_qoder(frm, subj, body)
                code = _extract_code(blob) if is_qoder else None
                if is_qoder and code:
                    verdict = "qoder"
                elif not is_qoder:
                    verdict = "skip-not-qoder"
                else:
                    verdict = "skip-no-code"
                path = _dump_mail(task_id, address, m, body, verdict)
                log(
                    task_id,
                    f"[mail] dump {verdict} from={str(frm)[:80]} subj={str(subj)[:80]} -> {path.name}",
                )
                if is_qoder and code:
                    log(task_id, f"[mail] verification code = {code}")
                    return code
                skipped += 1
            time.sleep(interval)
    finally:
        try:
            c.close()
        except Exception:
            pass
    raise TimeoutError(
        f"no qoder verification code within {timeout}s for {address} "
        f"(scanned={scanned} skipped={skipped})"
    )
