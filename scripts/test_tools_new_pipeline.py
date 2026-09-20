# -*- coding: utf-8 -*-
"""验证新管线下 qfmodel 工具调用（分片按 index 合并）。"""
import asyncio
import json
import sys

sys.path.insert(0, "src")

from qoder2api import bridge
from qoder2api.accounts import get_session_for_uid
from qoder2api.database import get_db

TOOLS = [{
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "查询指定城市的天气",
        "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
    },
}]


async def main() -> None:
    with get_db() as conn:
        row = conn.execute("SELECT uid FROM accounts WHERE enabled = 1 AND security_oauth_token != '' LIMIT 1").fetchone()
    sess = get_session_for_uid(row[0])
    req = {
        "model": "qfmodel",
        "messages": [{"role": "user", "content": "北京天气怎么样？必须调用 get_weather 工具查询，不要直接回答。"}],
        "stream": True,
        "tools": TOOLS,
    }
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
    print("content:", "".join(parts)[:120])
    merged = {}
    for c in calls:
        i = c.get("index", 0)
        m = merged.setdefault(i, {"id": "", "name": "", "args": ""})
        if c.get("id"):
            m["id"] = c["id"]
        fn = c.get("function") or {}
        if fn.get("name"):
            m["name"] = fn["name"]
        m["args"] += fn.get("arguments") or ""
    print("merged tool_calls:", merged)


if __name__ == "__main__":
    asyncio.run(main())
