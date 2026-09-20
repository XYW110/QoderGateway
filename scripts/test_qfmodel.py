# -*- coding: utf-8 -*-
"""用账号池里第一个可用账号测试 model key：qfmodel（对照组 lite）。

用法: python scripts/test_qfmodel.py [model_key ...]
默认测试 qfmodel + lite。
"""
import json
import sqlite3
import sys
import time
import uuid
from pathlib import Path

import httpx

DB_PATH = Path.home() / ".qoder" / "qoder2api.db"
URL = "https://api2-v2.qoder.sh/model/v1/chat/completions"


def pick_account() -> dict:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT uid, name, security_oauth_token FROM accounts "
        "WHERE enabled = 1 AND security_oauth_token IS NOT NULL AND security_oauth_token != '' "
        "LIMIT 1"
    ).fetchone()
    conn.close()
    if not row:
        raise SystemExit("账号池没有可用账号")
    return dict(row)


def test(model_key: str, tok: str) -> None:
    rid = str(uuid.uuid4())
    body = {
        "model": model_key,
        "messages": [{"role": "user", "content": "只回答一个词：你好"}],
        "stream": True,
        "stream_options": {"include_usage": True},
        "metadata": {
            "context": {
                "request_id": rid,
                "request_set_id": rid,
                "session_id": str(uuid.uuid4()),
                "task_id": "common",
                "client_type": "qodercli",
            }
        },
    }
    headers = {
        "Authorization": f"Bearer {tok}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "User-Agent": "qoder/1.1.16",
        "X-Request-ID": rid,
        "X-Session-ID": body["metadata"]["context"]["session_id"],
    }
    print(f"\n===== model={model_key} =====")
    t0 = time.time()
    try:
        with httpx.Client(timeout=120) as client:
            with client.stream("POST", URL, json=body, headers=headers) as resp:
                print(f"HTTP {resp.status_code}")
                if resp.status_code != 200:
                    print(resp.read().decode(errors="replace")[:500])
                    return
                text_parts = []
                usage = None
                for line in resp.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        obj = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    for ch in obj.get("choices", []):
                        d = ch.get("delta") or {}
                        if d.get("content"):
                            text_parts.append(d["content"])
                    if obj.get("usage"):
                        usage = obj["usage"]
                    if obj.get("model"):
                        last_model = obj["model"]
                print(f"耗时 {time.time()-t0:.1f}s")
                print(f"回复: {''.join(text_parts)[:200]!r}")
                print(f"响应 model 字段: {last_model if usage else '?'}")
                print(f"usage: credits={usage.get('credits')} total_tokens={usage.get('total_tokens')}" if usage else "无 usage")
    except Exception as exc:  # noqa: BLE001
        print(f"异常: {exc!r}")


if __name__ == "__main__":
    keys = sys.argv[1:] or ["qfmodel", "lite"]
    acc = pick_account()
    print(f"测试账号: {acc['name'] or acc['uid']}")
    for k in keys:
        test(k, acc["security_oauth_token"])
