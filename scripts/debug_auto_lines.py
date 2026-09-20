# -*- coding: utf-8 -*-
"""调试：auto 模型老版响应前几行到底是什么（带时间戳）。"""
import asyncio
import json
import os
import sys
import time

os.environ["QODER_FIRST_TOKEN_TIMEOUT"] = "5"
sys.path.insert(0, "src")

from qoder2api import bridge, encoding
from qoder2api.accounts import get_session_for_uid
from qoder2api.auth import bearer_headers
from qoder2api.bridge import QODER_CHAT_URL, template_base, blank_response_meta
from qoder2api.database import get_db
from qoder2api.env import httpx_client_kwargs

import httpx


async def main() -> None:
    model = sys.argv[1] if len(sys.argv) > 1 else "auto"
    with get_db() as conn:
        row = conn.execute("SELECT uid FROM accounts WHERE enabled = 1 AND security_oauth_token != '' LIMIT 1").fetchone()
    sess = get_session_for_uid(row[0])
    req = {"model": model, "messages": [{"role": "user", "content": "hi"}], "stream": True}
    body, _, _ = bridge.build_qoder_body(req, sess)
    payload = encoding.encode(json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode())
    headers = bearer_headers(sess, QODER_CHAT_URL, payload, "text/event-stream",
                             extra_headers={"X-Model-Key": model, "X-Model-Source": "system"})
    t0 = time.time()
    async with httpx.AsyncClient(timeout=httpx.Timeout(150, connect=10), **httpx_client_kwargs()) as c:
        async with c.stream("POST", QODER_CHAT_URL, content=payload, headers=headers) as r:
            print(f"HTTP {r.status_code} headers={dict(r.headers)}", flush=True)
            n = 0
            try:
                async for line in r.aiter_lines():
                    print(f"+{time.time()-t0:6.1f}s LINE[{n}] {line[:160]!r}", flush=True)
                    n += 1
                    if n >= 8:
                        break
            except Exception as e:
                print(f"+{time.time()-t0:6.1f}s EXC {e!r}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
