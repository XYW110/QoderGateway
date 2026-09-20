# -*- coding: utf-8 -*-
"""单个模型长超时单测（区分"慢"与"死"）。用法: python scripts/test_one_model.py <key> <timeout_s>"""
import asyncio
import json
import sys
import time

import httpx

sys.path.insert(0, "src")

from qoder2api import encoding
from qoder2api.accounts import get_session_for_uid
from qoder2api.auth import bearer_headers
from qoder2api.bridge import QODER_CHAT_URL, template_base, blank_response_meta
from qoder2api.database import get_db
from qoder2api.env import httpx_client_kwargs


async def main() -> None:
    key = sys.argv[1] if len(sys.argv) > 1 else "auto"
    secs = float(sys.argv[2]) if len(sys.argv) > 2 else 120
    with get_db() as conn:
        row = conn.execute("SELECT uid FROM accounts WHERE enabled = 1 AND security_oauth_token != '' LIMIT 1").fetchone()
    sess = get_session_for_uid(row[0])
    body = template_base()
    body["chat_context"]["extra"]["modelConfig"]["key"] = key
    body["model_config"]["key"] = key
    body["messages"].append({"role": "user", "content": "只回答一个词：你好",
                             "response_meta": blank_response_meta(), "reasoning_content_signature": ""})
    body["business"]["name"] = "test"
    payload = encoding.encode(json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode())
    headers = bearer_headers(sess, QODER_CHAT_URL, payload, "text/event-stream")
    headers["X-Model-Key"] = key
    headers["X-Model-Source"] = "system"
    print(f"model={key} timeout={secs}s", flush=True)
    t0 = time.time()
    parts, usage = [], None
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(secs, connect=10), **httpx_client_kwargs()) as c:
            async with c.stream("POST", QODER_CHAT_URL, content=payload, headers=headers) as r:
                print("HTTP", r.status_code, flush=True)
                async for line in r.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if raw == "[DONE]":
                        break
                    try:
                        obj = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    inner = obj.get("body")
                    if not inner:
                        continue
                    try:
                        chunk = json.loads(inner)
                    except json.JSONDecodeError:
                        continue
                    for ch in chunk.get("choices", []):
                        d = ch.get("delta") or {}
                        if d.get("content"):
                            parts.append(d["content"])
                    if chunk.get("usage"):
                        usage = chunk["usage"]
        print(f"耗时 {time.time()-t0:.1f}s 回复: {''.join(parts)[:100]!r} usage: {usage}", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"异常: {e!r} 已耗时 {time.time()-t0:.1f}s", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
