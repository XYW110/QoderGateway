# -*- coding: utf-8 -*-
"""
emailnator_client.py - Emailnator 官方 API 可编程临时邮箱客户端
====================================================================
针对新版网站（Next.js 16.3 + Turbopack 重写）手动逆向实现，已实测通过。

实测结论（2026-09-12）：
  * 新版站点首页不返回任何 Set-Cookie，旧版 XSRF-TOKEN cookie 方案已彻底废弃；
  * 所有 /api/* 端点【无需任何鉴权】（无 cookie / 无 header / 无 token）；
  * wrapper(pyPI emailnator-wrapper 2.1.0) 仍走旧端点 /generate-email,/message-list
    与 XSRF 方案，对新版 404 已失效 —— 本项目不依赖它。

真实前端契约（从 2e_lrwr-bf1eq.js / emailnator_chunks.js 提取）：
  POST /api/generate-email        body {"ids":[..]}                   生成 1 个
  POST /api/generate-bulk-email   body {"ids":[..],"count":N}         批量生成
  POST /api/message-list          body {"email":E,"limit":20}         收件箱列表
  POST /api/extend-email          body {"email":E}                    延长有效期
  GET  /api/message/<messageID>                                       单封内容(HTML)
  DELETE /api/delete-message/<messageID>                              删除一封
  EMAIL_TYPES = {domain:1, plusGmail:2, dotGmail:3, googleMail:8}

环境纪律：必须走本地 Clash 代理 127.0.0.1:7897（裸 IP 直连会被拦截）。

对外方法（供下游复用）：
  generate_email(plus=True, dot=True, googlemail=False) -> str
  message_list(email) -> list[dict]
  get_message(email, msg_id) -> str
  extend_email(email) / bulk_emails(ids, count) -> list
"""
import os
import re
import time
import json
import httpx

BASE = "https://www.emailnator.com"


def _default_proxy() -> str:
    """代理运行时从环境变量读取（.env 由 qoder2api.env 在导入期加载）：
    LOCAL_PROXY > QODER_PROXY > 默认 Clash 7897。"""
    return (os.environ.get("LOCAL_PROXY") or os.environ.get("QODER_PROXY")
            or "http://127.0.0.1:7897").strip()


# 兼容旧引用（模块导入期的快照；客户端默认代理以 _default_proxy() 实时读取为准）
PROXY = _default_proxy()

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# 前端 EMAIL_TYPES 常量（chunk 提取）
EMAIL_TYPES = {"domain": 1, "plusGmail": 2, "dotGmail": 3, "googleMail": 8}


class EmailnatorAPIError(Exception):
    """Emailnator API 返回非 2xx 或异常结构时抛出"""


class EmailnatorClient:
    """Emailnator 官方内部 API 客户端（httpx，走本地 Clash 代理）。"""

    def __init__(self, proxy: str | None = None, timeout: float = 25.0):
        # 默认走 _default_proxy()（.env 的 LOCAL_PROXY/QODER_PROXY），
        # Emailnator 裸 IP 直连会被拦截
        self._client = httpx.Client(
            proxy=proxy or _default_proxy(),
            timeout=timeout,
            headers={
                "User-Agent": UA,
                "Accept": "application/json, text/plain, */*",
                "Content-Type": "application/json",
                "Origin": BASE,
                "Referer": BASE + "/",
            },
        )

    # ---------- 底层请求 ----------
    def _request(self, method: str, path: str, **kw):
        try:
            resp = self._client.request(method, BASE + path, **kw)
        except httpx.HTTPError as e:
            raise EmailnatorAPIError(f"{method} {path} 网络错误: {e}") from e
        try:
            data = resp.json()
        except Exception:
            data = None
        if resp.status_code >= 400:
            msg = (data or {}).get("message") or (data or {}).get("error") or \
                f"HTTP {resp.status_code}"
            raise EmailnatorAPIError(f"{method} {path} -> {resp.status_code}: {msg}")
        return resp.status_code, data

    # ---------- 生成邮箱 ----------
    def generate_email(
        self,
        plus: bool = True,
        dot: bool = True,
        googlemail: bool = False,
        domain: bool = False,
        gmail_only: bool = True,
        retries: int = 8,
    ) -> str:
        """生成邮箱。生产默认 plus+dot（@gmail.com），不混 domain 临时域。
        gmail_only=True 时若抽到非 gmail 会重试。domain=True 才生成自有域。"""
        ids = []
        if domain:
            ids.append(EMAIL_TYPES["domain"])
        if plus:
            ids.append(EMAIL_TYPES["plusGmail"])
        if dot:
            ids.append(EMAIL_TYPES["dotGmail"])
        if googlemail:
            ids.append(EMAIL_TYPES["googleMail"])
        if not ids:
            ids = [EMAIL_TYPES["domain"]]
        last = None
        for _ in range(max(1, retries)):
            code, data = self._request("POST", "/api/generate-email",
                                       json={"ids": ids})
            email = (data or {}).get("email")
            if not email or not isinstance(email, str) or "@" not in email:
                raise EmailnatorAPIError(
                    f"generate-email 响应异常: code={code} data={data}")
            last = email
            host = email.rsplit("@", 1)[-1].lower()
            if gmail_only and host not in ("gmail.com", "googlemail.com"):
                continue
            return email
        return last

    def generate_bulk(self, count: int = 100,
                      plus: bool = True, dot: bool = True) -> list[str]:
        """批量生成（count 用字符串，符合前端 "100"/"200"/"300"）。"""
        ids = [EMAIL_TYPES["domain"]]
        if plus:
            ids.append(EMAIL_TYPES["plusGmail"])
        if dot:
            ids.append(EMAIL_TYPES["dotGmail"])
        code, data = self._request(
            "POST", "/api/generate-bulk-email",
            json={"ids": ids, "count": str(count)})
        emails = (data or {}).get("emails") or (data or {}).get("emailData") or []
        if not emails:
            raise EmailnatorAPIError(f"bulk 响应异常: code={code} data={data}")
        return emails if isinstance(emails, list) else [emails]

    # ---------- 收件箱 ----------
    def message_list(self, email: str) -> list[dict]:
        """查询收件箱列表。返回 [{messageID, from, subject, time, ...}, ...]（可能为空）。
        关键验收：HTTP 2xx 即算通。"""
        code, data = self._request(
            "POST", "/api/message-list", json={"email": email, "limit": 20})
        # 实测契约（2026-09-13 dump）：
        #   {"status":"success","messages":[...],"message_count":N,"message_limit":10,"upgrade_available":true}
        # 旧字段 messageData 保留兼容。
        if isinstance(data, list):
            return data
        if not isinstance(data, dict):
            raise EmailnatorAPIError(f"message-list 结构异常: code={code} data={data}")
        for key in ("messages", "messageData", "data"):
            val = data.get(key)
            if isinstance(val, list):
                return val
        if data.get("status") == "success":
            return []
        raise EmailnatorAPIError(f"message-list 结构异常: code={code} data={data}")

    # ---------- 单封内容 ----------
    @staticmethod
    def msg_id(msg: dict) -> str:
        """列表项主键：实测字段是 id（不是 messageID）。"""
        return (msg or {}).get("id") or (msg or {}).get("messageID") or ""

    def get_message(self, email: str, msg_id: str) -> str:
        """读取单封邮件 HTML 正文。实测 GET /api/message/<id> 返回 JSON，
        正文在 content 字段。兼容直接返回 HTML 的旧形态。"""
        try:
            resp = self._client.get(
                BASE + "/api/message/" + _enc(msg_id),
                headers={"Accept": "application/json, text/html,*/*"})
            if resp.status_code == 200:
                body = resp.text
                try:
                    obj = resp.json()
                except Exception:
                    obj = None
                if isinstance(obj, dict) and obj.get("content"):
                    return obj["content"]
                if isinstance(obj, dict) and obj.get("html"):
                    return obj["html"]
                return body
        except httpx.HTTPError:
            pass
        code, data = self._request(
            "POST", "/api/message-list",
            json={"email": email, "messageID": msg_id})
        if isinstance(data, str):
            return data
        if isinstance(data, dict):
            for k in ("content", "html", "messageData", "body"):
                if isinstance(data.get(k), str) and data[k]:
                    return data[k]
        raise EmailnatorAPIError(
            f"get_message 响应异常: code={code} data={str(data)[:200]}")

    def wait_messages(self, email: str, timeout: float = 90.0,
                      interval: float = 3.0) -> list[dict]:
        """轮询直到 inbox 非空或超时。返回 messages（可能为空）。"""
        deadline = time.time() + timeout
        last = []
        while time.time() < deadline:
            last = self.message_list(email)
            if last:
                return last
            time.sleep(interval)
        return last

    # ---------- 其它 ----------
    def extend_email(self, email: str) -> dict:
        """延长邮箱有效期。"""
        code, data = self._request("POST", "/api/extend-email",
                                   json={"email": email})
        return data

    def delete_message(self, msg_id: str) -> dict:
        """删除一封邮件。"""
        self._client.headers.pop("Content-Type", None)
        try:
            resp = self._client.request(
                "DELETE", BASE + "/api/delete-message/" + _enc(msg_id))
        finally:
            self._client.headers["Content-Type"] = "application/json"
        if resp.status_code < 400:
            try:
                return resp.json()
            except Exception:
                return {}
        raise EmailnatorAPIError(
            f"delete-message -> {resp.status_code}: {resp.text[:200]}")

    def close(self):
        self._client.close()


def _enc(s: str) -> str:
    from urllib.parse import quote
    return quote(s, safe="")
