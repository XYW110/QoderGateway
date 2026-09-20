# -*- coding: utf-8 -*-
"""老版协议切换后的端到端验证。

1) stream_openai_response(lite)      → 有内容
2) complete_openai_response(qfmodel) → 有内容（非流式）
3) stream_openai_response(qfmodel+tools) → tool_calls 分片可合并
4) 挂起判定：FIRST_TOKEN_TIMEOUT=5 时请求 auto → UpstreamHangError（~5s）
5) is_account_error(UpstreamHangError) → True（触发轮换）
"""
import asyncio
import json
import os
import sys
import time

os.environ["QODER_FIRST_TOKEN_TIMEOUT"] = "5"  # 挂起测试用短超时

sys.path.insert(0, "src")

from qoder2api import bridge
from qoder2api.accounts import get_session_for_uid
from qoder2api.app import is_account_error
from qoder2api.database import get_db
from qoder2api.bridge import UpstreamHangError

TOOLS = [{
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "查询指定城市的天气",
        "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
    },
}]


def pick_session():
    with get_db() as conn:
        row = conn.execute("SELECT uid FROM accounts WHERE enabled = 1 AND security_oauth_token != '' LIMIT 1").fetchone()
    return get_session_for_uid(row[0])


async def t_stream(model: str, tools=None) -> str:
    req = {"model": model, "messages": [{"role": "user", "content": "只回答一个词：你好"}], "stream": True}
    if tools:
        req["tools"] = tools
    sess = pick_session()
    parts, calls = [], []
    async for line in bridge.stream_openai_response(req, sess):
        if not line.startswith("data:"):
            continue
        p = line[5:].strip()
        if p == "[DONE]":
            break
        obj = json.loads(p)
        for ch in obj.get("choices", []):
            d = ch.get("delta") or {}
            if d.get("content"):
                parts.append(d["content"])
            if d.get("tool_calls"):
                calls.extend(d["tool_calls"])
    text = "".join(parts)
    print(f"[stream {model}] content={text[:80]!r} tool_call_fragments={len(calls)} model_echo={obj.get('model')}")
    return text, calls


async def t_nonstream(model: str) -> str:
    req = {"model": model, "messages": [{"role": "user", "content": "只回答一个词：你好"}], "stream": False}
    sess = pick_session()
    resp = await bridge.complete_openai_response(req, sess)
    msg = resp["choices"][0]["message"]
    print(f"[non-stream {model}] content={str(msg.get('content'))[:80]!r} finish={resp['choices'][0]['finish_reason']} model_echo={resp['model']}")
    return msg.get("content") or ""


async def t_hang() -> None:
    req = {"model": "auto", "messages": [{"role": "user", "content": "hi"}], "stream": True}
    sess = pick_session()
    t0 = time.time()
    try:
        async for _ in bridge.stream_openai_response(req, sess):
            pass
        print("[hang] 未抛异常（意外）")
    except (UpstreamHangError, bridge.UpstreamErrorFrame) as e:
        print(f"[hang] {time.time()-t0:.1f}s 抛 {type(e).__name__}: {str(e)[:200]}")
        print(f"[hang] is_account_error -> {is_account_error(e)}")


async def main() -> None:
    print(f"USE_OLD_PROTOCOL={bridge.USE_OLD_PROTOCOL} FIRST_TOKEN_TIMEOUT={bridge.FIRST_TOKEN_TIMEOUT}")
    await t_stream("lite")
    await t_nonstream("qfmodel")
    text, calls = await t_stream("qfmodel", tools=TOOLS)
    await t_hang()


if __name__ == "__main__":
    asyncio.run(main())
