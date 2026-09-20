# -*- coding: utf-8 -*-
"""email_api.py - 统一邮箱 API（双后端，代理分离）。

注：原独立模块收编进 qoder2api.mail_client 包，供 exe/Docker 一并打包。
"""
import re
import time

from .emailnator_client import EmailnatorClient, _default_proxy

# 兼容旧引用；实际取值在每次调用时经 _default_proxy() 实时读取
def _local_proxy() -> str:
    return _default_proxy()


def _digit_code(content):
    if not content:
        return None
    m = re.search(r"(?i)(?:code|verification|verify|captcha)?\D{0,8}(\d{6})\D{0,3}", content)
    if m:
        return m.group(1)
    m = re.search(r"(?<!\d)(\d{6})(?!\d)", content)
    return m.group(1) if m else None


def generate_email(backend="emailnator", gmail_only=True):
    if backend.lower() in ("emailnator", "en"):
        c = EmailnatorClient(proxy=_local_proxy())
        try:
            email = c.generate_email(domain=False, gmail_only=gmail_only)
            return email, "emailnator"
        finally:
            c.close()
    raise ValueError(f"unknown backend generate_email: {backend}")


def _msg_ts(m):
    try:
        return float((m or {}).get("timestamp"))
    except Exception:
        return None


def read_code(email, backend="emailnator", timeout=90.0, interval=2.5, since=None,
              priority_hints=("amd",)):
    """收码。注意：emailnator 地址是【共享收件箱】（实测满是他人邮件），必须过滤：
    ① 只认「发码时刻之后到达」的邮件(since，留 10s 余量吸收时钟偏差)；
    ② 优先发件人/主题命中 priority_hints 的邮件；③ 其余按到达时间从新到旧；
    ④ 跳过 locked（无正文）。"""
    if backend.lower() in ("emailnator", "en"):
        c = EmailnatorClient(proxy=_local_proxy())
        try:
            deadline = time.time() + timeout
            seen = set()
            while time.time() < deadline:
                msgs = c.message_list(email)
                cands = []
                for m in msgs:
                    mid = EmailnatorClient.msg_id(m)
                    if not mid or m.get("locked"):
                        continue
                    ts = _msg_ts(m)
                    if since is not None:
                        if ts is None:
                            continue                 # 有 since 时，无时间戳的不敢信
                        if ts < (since - 10.0):
                            continue                 # 早于发码时刻 -> 他人旧邮件，忽略
                    cands.append((ts if ts is not None else 0.0, mid, m))
                blob_l = lambda m: ((m.get("from") or "") + " " + (m.get("subject") or "")).lower()
                # 排序键：先「发件人/主题命中提示词」，再「到达时间新->旧」
                cands.sort(key=lambda x: (
                    0 if any(h in blob_l(x[2]) for h in priority_hints) else 1,
                    -x[0]))
                for _ts, mid, m in cands:
                    if mid in seen:
                        continue
                    seen.add(mid)
                    subj = (m.get("subject") or "") + " " + (m.get("from") or "")
                    try:
                        body = c.get_message(email, mid)
                    except Exception:
                        continue
                    code = _digit_code(body) or _digit_code(subj)
                    if code and len(code) == 6:
                        return code
                time.sleep(interval)
            return None
        finally:
            c.close()
    raise ValueError(f"unknown backend read_code: {backend}")
