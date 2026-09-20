# -*- coding: utf-8 -*-
"""固定 qfmodel：老版协议对话 + 工具调用测试。

- 第一轮：带 tools 的对话，验证 tool_calls 是否正常回传（分片按 index 合并）
- 第二轮：回填 tool 结果，验证多轮工具对话闭环
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

MODEL_KEY = "qfmodel"

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "查询指定城市的天气",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string", "description": "城市名"}},
                "required": ["city"],
            },
        },
    }
]


def build_body(messages: list, tools: list) -> dict:
    body = template_base()
    body["chat_context"]["extra"]["modelConfig"]["key"] = MODEL_KEY
    body["model_config"]["key"] = MODEL_KEY
    body["messages"] = [
        {
            "role": "system",
            "content": "You are Qoder, an interactive CLI tool that helps users with software engineering tasks.",
            "response_meta": blank_response_meta(),
            "reasoning_content_signature": "",
        }
    ] + messages
    body["tools"] = tools
    body["business"]["name"] = "tool-test"
    return body


def msg(m) -> dict:
    return {"role": m["role"], "content": m["content"], "response_meta": blank_response_meta(),
            "reasoning_content_signature": ""}


def merge_calls(raw_calls: list) -> list:
    merged: dict[int, dict] = {}
    for c in raw_calls:
        idx = c.get("index", 0)
        if idx not in merged:
            merged[idx] = {"id": "", "type": "function", "index": idx, "function": {"name": "", "arguments": ""}}
        m = merged[idx]
        if c.get("id"):
            m["id"] = c["id"]
        fn = c.get("function") or {}
        if fn.get("name"):
            m["function"]["name"] = fn["name"]
        if fn.get("arguments"):
            m["function"]["arguments"] += fn["arguments"]
    return [m for m in merged.values() if m["function"]["name"]]


async def chat(sess, messages: list, tools: list, tag: str) -> dict:
    body = build_body(messages, tools)
    payload = encoding.encode(json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode())
    headers = bearer_headers(sess, QODER_CHAT_URL, payload, "text/event-stream")
    headers["X-Model-Key"] = MODEL_KEY
    headers["X-Model-Source"] = "system"
    print(f"\n===== {tag} =====")
    t0 = time.time()
    text_parts, raw_calls, usage = [], [], None
    resp_model = None
    raw_frames = []
    async with httpx.AsyncClient(timeout=httpx.Timeout(180, connect=15), **httpx_client_kwargs()) as client:
        async with client.stream("POST", QODER_CHAT_URL, content=payload, headers=headers) as resp:
            print(f"HTTP {resp.status_code}")
            if resp.status_code != 200:
                print((await resp.aread()).decode(errors="replace")[:400])
                return {}
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
                if chunk.get("model"):
                    resp_model = chunk["model"]
                for ch in chunk.get("choices", []):
                    d = ch.get("delta") or {}
                    if d.get("content"):
                        text_parts.append(d["content"])
                    if d.get("tool_calls"):
                        raw_calls.extend(d["tool_calls"])
                if chunk.get("usage"):
                    usage = chunk["usage"]
                if not (text_parts or raw_calls or usage):
                    raw_frames.append(inner[:200])
    tool_calls = merge_calls(raw_calls)
    print(f"耗时 {time.time()-t0:.1f}s")
    print(f"文本: {''.join(text_parts)[:300]!r}")
    print(f"tool_calls(合并后): {json.dumps(tool_calls, ensure_ascii=False)[:500]}")
    print(f"响应 model: {resp_model}  usage: {usage}")
    if raw_frames:
        print(f"空内容帧数: {len(raw_frames)}，首帧: {raw_frames[0][:200]}")
    return {"text": "".join(text_parts), "tool_calls": tool_calls, "usage": usage}


async def main() -> None:
    with get_db() as conn:
        row = conn.execute("SELECT uid FROM accounts WHERE enabled = 1 AND security_oauth_token != '' LIMIT 1").fetchone()
    sess = get_session_for_uid(row[0])
    print(f"账号: {sess.identity.name} / model key: {MODEL_KEY}")

    r1 = await chat(sess, [msg({"role": "user", "content": "北京现在天气怎么样？请调用工具查询。"})], TOOLS,
                    "第一轮：带 tools 对话")
    if not r1.get("tool_calls"):
        print("\n第一轮未产生 tool_calls，跳过第二轮。")
        return
    messages = [
        msg({"role": "user", "content": "北京现在天气怎么样？请调用工具查询。"}),
        {"role": "assistant", "content": "", "tool_calls": r1["tool_calls"],
         "response_meta": blank_response_meta(), "reasoning_content_signature": ""},
        {"role": "tool", "tool_call_id": r1["tool_calls"][0].get("id", ""), "content": "晴，25℃，微风",
         "response_meta": blank_response_meta(), "reasoning_content_signature": ""},
    ]
    await chat(sess, messages, TOOLS, "第二轮：回填 tool 结果")


if __name__ == "__main__":
    asyncio.run(main())
