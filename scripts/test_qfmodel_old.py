# -*- coding: utf-8 -*-
"""老版协议（api3 agent_chat_generation + COSY 签名）多模型实测。

用法: python scripts/test_qfmodel_old.py [model_key ...]
默认测试 QODER_MODELS 全目录 + qfmodel。
单账号；单请求 90s 超时；输出 flush 便于后台跑看日志。
"""
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

DEFAULT_KEYS = [
    "auto", "ultimate", "performance", "efficient", "lite",
    "qmodel", "qmodel_latest", "dmodel", "dfmodel", "gm51model", "kmodel", "mmodel",
    "qfmodel",
]


def build_body(model_key: str) -> dict:
    body = template_base()
    body["chat_context"]["extra"]["modelConfig"]["key"] = model_key
    body["model_config"]["key"] = model_key
    body["messages"].append({
        "role": "user",
        "content": "只回答一个词：你好",
        "response_meta": blank_response_meta(),
        "reasoning_content_signature": "",
    })
    body["business"]["name"] = "test"
    return body


async def test(model_key: str, sess) -> None:
    body = build_body(model_key)
    payload = encoding.encode(json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode())
    headers = bearer_headers(sess, QODER_CHAT_URL, payload, "text/event-stream")
    headers["X-Model-Key"] = model_key
    headers["X-Model-Source"] = "system"
    print(f"\n===== model={model_key} =====", flush=True)
    t0 = time.time()
    parts, usage = [], None
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30, connect=10), **httpx_client_kwargs()) as client:
            async with client.stream("POST", QODER_CHAT_URL, content=payload, headers=headers) as resp:
                print(f"HTTP {resp.status_code}", flush=True)
                if resp.status_code != 200:
                    print((await resp.aread()).decode(errors="replace")[:400], flush=True)
                    return
                async for line in resp.aiter_lines():
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
    except Exception as exc:  # noqa: BLE001
        print(f"异常/超时: {exc!r}", flush=True)
        return
    print(f"耗时 {time.time()-t0:.1f}s", flush=True)
    print(f"回复: {''.join(parts)[:200]!r}", flush=True)
    if usage:
        print(f"usage: credits={usage.get('credits')} total_tokens={usage.get('total_tokens')}", flush=True)


async def main() -> None:
    keys = sys.argv[1:] or DEFAULT_KEYS
    with get_db() as conn:
        row = conn.execute("SELECT uid FROM accounts WHERE enabled = 1 AND security_oauth_token != '' LIMIT 1").fetchone()
    sess = get_session_for_uid(row[0])
    print(f"测试账号: {sess.identity.name} ({sess.identity.uid})", flush=True)
    print(f"待测模型: {keys}", flush=True)
    for k in keys:
        await test(k, sess)


if __name__ == "__main__":
    asyncio.run(main())
