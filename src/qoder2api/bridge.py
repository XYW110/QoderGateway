import asyncio
import copy
import json
import os
import threading
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

from . import encoding
from .auth import SessionContext, bearer_headers
from .env import httpx_client_kwargs, proxy_url


QODER_CHAT_URL = "https://api3.qoder.sh/algo/api/v2/service/pro/sse/agent_chat_generation?FetchKeys=llm_model_result&AgentId=agent_common&Encode=1"
# 新版协议（Qoder CLI 现行）：OpenAI 兼容端点，纯 Bearer，无 COSY 签名，响应为标准 OpenAI SSE。
# 性能远优于老版（老版默认带长 reasoning，复杂任务可到分钟级）。
# 当前不作为主路径：实测非 lite 模型在新版通道全部 402，详见 docs/qoder-protocol-research.md §10。
# 未来新版全模型可用后，把 QODER_USE_OLD_PROTOCOL 置 0 即可切回。
QODER_CHAT_URL_NEW = "https://api2-v2.qoder.sh/model/v1/chat/completions"

# 协议路由：默认全部模型走老版 api3（COSY 签名 + X-Model-Key + encoding.encode）。
USE_OLD_PROTOCOL = os.getenv("QODER_USE_OLD_PROTOCOL", "1").strip().lower() not in {"0", "false", "no", "off"}
# 首字超时：老版协议对无权限/无配额的模型不报错、无限挂起（HTTP 200 后零字节），
# 必须靠首字超时判定"挂起"并触发账号轮换，否则连接被无限占用。
FIRST_TOKEN_TIMEOUT = float(os.getenv("QODER_FIRST_TOKEN_TIMEOUT", "60"))
# 流中读超时：首字之后单个 chunk 间隔上限，防半路挂起。
STREAM_READ_TIMEOUT = float(os.getenv("QODER_STREAM_READ_TIMEOUT", "120"))
# 非流式总超时。
TOTAL_TIMEOUT = float(os.getenv("QODER_TOTAL_TIMEOUT", "300"))
# 上游连接池（共享 AsyncClient）：复用 TLS 连接，避免每请求新建 client 的握手/句柄 churn。
HTTP_MAX_CONNECTIONS = int(os.getenv("QODER_HTTP_MAX_CONNECTIONS", "200"))
HTTP_MAX_KEEPALIVE = int(os.getenv("QODER_HTTP_KEEPALIVE", "100"))
# 单账号并发闸：同一账号同时在飞的上游请求上限（上游对单账号配额/并发有限）。
ACCOUNT_CONCURRENCY = max(1, int(os.getenv("QODER_ACCOUNT_CONCURRENCY", "4")))
# 拿不到账号槽位时的最长等待秒数（超时算临时错误，不轮换账号）。
ACCOUNT_SLOT_WAIT = float(os.getenv("QODER_ACCOUNT_SLOT_WAIT", "30"))


class UpstreamHangError(RuntimeError):
    """上游挂起：HTTP 200 但首字超时（老版协议对无配额模型的典型失败模式）。

    消息中固定含 "hang" / "first token" 关键词，app.is_account_error 据此判定为
    账号级错误并轮换下一个账号。
    """


class UpstreamErrorFrame(RuntimeError):
    """老版协议 SSE 错误帧：data 包裹的 body 内含 code/message 而非 choices。

    实测无配额/无权限模型（auto/ultimate/... 11 个）会立即返回此类帧
    （如 code=112 + pricingUrl），随后不再吐字。必须识别为账号级错误并轮换，
    否则会被当成空流干等读超时。
    """

# Qoder 模型 key 清单（参照 mydisha/keirouter 的 qoder provider 模型目录）：
# 前 5 个为档位模型，后 7 个为 frontier 模型。仅用于 /v1/models 发现端点与
# 前端 Playground 下拉提示；chat 请求的 model 仍为透传（不做硬校验）。
QODER_MODELS: list[dict[str, str]] = [
    # qfmodel：Qoder IDE（0.3.4+）默认模型 key，2026-09-20 抓包发现，不在 keirouter 目录中
    {"id": "qfmodel", "name": "Qoder (IDE 默认)"},
    {"id": "auto", "name": "Auto"},
    {"id": "ultimate", "name": "Ultimate"},
    {"id": "performance", "name": "Performance"},
    {"id": "efficient", "name": "Efficient"},
    {"id": "lite", "name": "Lite"},
    {"id": "qmodel", "name": "Q Model"},
    {"id": "qmodel_latest", "name": "Q Model (Latest)"},
    {"id": "dmodel", "name": "D Model"},
    {"id": "dfmodel", "name": "DF Model"},
    {"id": "gm51model", "name": "GM 5.1 Model"},
    {"id": "kmodel", "name": "K Model"},
    {"id": "mmodel", "name": "M Model"},
]


def now_ms() -> int:
    return int(time.time() * 1000)


def blank_response_meta() -> dict[str, Any]:
    return {
        "id": "",
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "completion_tokens_details": {"reasoning_tokens": 0},
            "prompt_tokens_details": {"cached_tokens": 0},
        },
    }


def template_base() -> dict[str, Any]:
    return {
        "request_id": str(uuid.uuid4()),
        "request_set_id": str(uuid.uuid4()),
        "chat_record_id": str(uuid.uuid4()),
        "stream": True,
        "chat_task": "FREE_INPUT",
        "chat_context": {
            "chatPrompt": "",
            "extra": {"context": [], "modelConfig": {"is_reasoning": False, "key": "lite"}, "originalContent": {"type": "text", "text": "hi"}},
            "features": [],
            "imageUrls": None,
            "text": {"type": "text", "text": "hi"},
        },
        "image_urls": None,
        "is_reply": True,
        "is_retry": False,
        "session_id": str(uuid.uuid4()),
        "code_language": "",
        "source": 1,
        "version": "3",
        "chat_prompt": "",
        "parameters": {"max_tokens": 32768},
        "aliyun_user_type": "personal_standard",
        "session_type": "qodercli",
        "agent_id": "agent_common",
        "task_id": "common",
        "model_config": {
            "key": "lite",
            "display_name": "Lite",
            "model": "",
            "format": "openai",
            "is_vl": False,
            "is_reasoning": False,
            "api_key": "",
            "url": "",
            "source": "system",
            "max_input_tokens": 180000,
        },
        "messages": [
            {
                "role": "system",
                "content": "You are Qoder, an interactive CLI tool that helps users with software engineering tasks.",
                "response_meta": blank_response_meta(),
                "reasoning_content_signature": "",
            }
        ],
        "tools": [],
        "business": {"product": "cli", "version": "0.1.43", "type": "agent", "id": str(uuid.uuid4()), "name": "hi", "begin_at": now_ms(), "stage": "start"},
    }


def normalize_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [normalize_content_part(item) for item in content]
        return "\n\n".join(part for part in parts if part.strip())
    return normalize_content_part(content)


def normalize_content_part(item: Any) -> str:
    if item is None:
        return ""
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        if isinstance(item.get("text"), str):
            return item["text"]
        if item.get("type") in {"image_url", "input_image"} and isinstance(item.get("image_url"), dict):
            url = item["image_url"].get("url")
            if isinstance(url, str):
                return f"[image] {url}"
        if isinstance(item.get("content"), (dict, list)):
            return normalize_content(item["content"])
        return json.dumps(item, ensure_ascii=False)
    return json.dumps(item, ensure_ascii=False)


def normalize_message_text(message: dict[str, Any]) -> str:
    text = normalize_content(message.get("content"))
    return text if text.strip() else normalize_content(message.get("contents"))


def extract_latest_user_prompt(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages or []):
        if message.get("role") == "user":
            text = normalize_message_text(message)
            if text.strip():
                return text
    return ""


def build_user_message(text: str) -> dict[str, Any]:
    return {
        "role": "user",
        "content": "",
        "contents": [{"type": "text", "text": text}],
        "response_meta": blank_response_meta(),
        "reasoning_content_signature": "",
    }


def build_structured_message(role: str, text: str) -> dict[str, Any]:
    return {"role": role, "content": text or "", "response_meta": blank_response_meta(), "reasoning_content_signature": ""}


def normalize_tool_arguments(arguments: Any) -> str:
    if arguments is None:
        return ""
    if isinstance(arguments, str):
        return arguments
    return json.dumps(arguments, ensure_ascii=False, separators=(",", ":"))


def normalize_tool_calls(raw_tool_calls: Any) -> list[dict[str, Any]] | None:
    if not isinstance(raw_tool_calls, list):
        return None
    normalized = []
    for raw in raw_tool_calls:
        function = raw.get("function", {}) if isinstance(raw, dict) else {}
        name = function.get("name", "")
        arguments = normalize_tool_arguments(function.get("arguments"))
        if not name and not arguments:
            continue
        normalized.append({"id": raw.get("id", ""), "type": raw.get("type", "function"), "function": {"name": name, "arguments": arguments}})
    return normalized or None


def parse_tool_calls_text(text: str | None) -> list[dict[str, Any]] | None:
    if not text:
        return None
    trimmed = text.strip()
    if not trimmed.startswith("Tool calls:"):
        return None
    payload = trimmed[len("Tool calls:") :].strip()
    if payload.startswith("```") and payload.endswith("```"):
        newline = payload.find("\n")
        if newline >= 0:
            payload = payload[newline + 1 : -3].strip()
    if not payload.startswith("["):
        return None
    try:
        return normalize_tool_calls(json.loads(payload))
    except json.JSONDecodeError:
        return None


def render_tool_result(message: dict[str, Any], text: str) -> str:
    label = "Tool result"
    if message.get("name"):
        label += f" ({message['name']})"
    if message.get("tool_call_id"):
        label += f" [{message['tool_call_id']}]"
    return f"{label}:\n{text}" if text.strip() else label


def convert_incoming_message(message: dict[str, Any], tools_enabled: bool) -> dict[str, Any] | None:
    role = message.get("role", "user")
    text = normalize_message_text(message)
    if not tools_enabled and message.get("tool_calls"):
        calls = json.dumps(message["tool_calls"], ensure_ascii=False)
        text = f"{text}\n\nTool calls:\n{calls}" if text.strip() else f"Tool calls:\n{calls}"
    if role == "tool":
        if tools_enabled:
            out = build_structured_message("tool", text)
            if message.get("name"):
                out["name"] = message["name"]
            if message.get("tool_call_id"):
                out["tool_call_id"] = message["tool_call_id"]
            return out
        role = "user"
        text = render_tool_result(message, text)
    if not text.strip() and not (tools_enabled and role == "assistant" and message.get("tool_calls")):
        return None
    if role == "user":
        return build_user_message(text)
    out = build_structured_message(role, text)
    if tools_enabled and role == "assistant":
        tool_calls = normalize_tool_calls(message.get("tool_calls")) or parse_tool_calls_text(text)
        if tool_calls:
            out["tool_calls"] = tool_calls
            if parse_tool_calls_text(text):
                out["content"] = ""
    return out


def build_qoder_messages(template_messages: list[dict[str, Any]], incoming: list[dict[str, Any]], prompt: str, tools_enabled: bool) -> list[dict[str, Any]]:
    rebuilt = []
    if not any(message.get("role") == "system" for message in incoming or []):
        rebuilt.extend(copy.deepcopy(message) for message in template_messages if message.get("role") == "system")
    for message in incoming or []:
        converted = convert_incoming_message(message, tools_enabled)
        if converted:
            rebuilt.append(converted)
    if not rebuilt and prompt.strip():
        rebuilt.append(build_user_message(prompt))
    return rebuilt


def build_qoder_body(req: dict[str, Any], sess: SessionContext) -> tuple[dict[str, Any], str, bool]:
    """老版协议 body：template_base() 骨架 + model key 双写 + OpenAI messages/tools 转换。

    model key 必须同时写入 model_config.key 与 chat_context.extra.modelConfig.key，
    并随请求头 X-Model-Key 一起下发（与 Qoder IDE 实测一致）。
    消息转换复用 build_qoder_messages（system 注入 / tool 消息 / tool_calls 归一化）。
    """
    model = req.get("model") or "lite"
    messages = req.get("messages") if isinstance(req.get("messages"), list) else []
    tools_enabled = bool(req.get("tools"))

    body = template_base()
    body["chat_context"]["extra"]["modelConfig"]["key"] = model
    body["chat_context"]["extra"]["modelConfig"]["display_name"] = model
    body["model_config"]["key"] = model
    body["model_config"]["display_name"] = model
    body["model_config"]["source"] = "system"
    body["session_id"] = str(uuid.uuid4())
    body["business"]["name"] = "qoder2api"
    prompt = extract_latest_user_prompt(messages)
    body["chat_context"]["chatPrompt"] = prompt
    body["chat_context"]["text"] = {"type": "text", "text": prompt}
    system_messages = [m for m in body["messages"] if m.get("role") == "system"]
    body["messages"] = build_qoder_messages(system_messages, messages, prompt, tools_enabled)
    body["tools"] = copy.deepcopy(req["tools"]) if tools_enabled else []
    max_tokens = req.get("max_tokens")
    if isinstance(max_tokens, int) and max_tokens > 0:
        body["parameters"]["max_tokens"] = max_tokens
    return body, model, tools_enabled


@dataclass
class BridgeDelta:
    role: str = ""
    content: str = ""
    tool_calls: list[dict[str, Any]] | None = None

    @property
    def is_empty(self) -> bool:
        return not self.role and not self.content and not self.tool_calls


def extract_delta(data_line: str) -> BridgeDelta:
    try:
        obj = json.loads(data_line)
        if not isinstance(obj, dict):
            return BridgeDelta()
        # 新版：标准 OpenAI chunk（choices 直接在顶层）
        if "choices" in obj:
            for choice in obj.get("choices", []):
                delta = choice.get("delta", {}) if isinstance(choice, dict) else {}
                role = delta.get("role") or ""
                content = delta.get("content") or ""
                tool_calls = delta.get("tool_calls") if isinstance(delta.get("tool_calls"), list) else None
                if role or content or tool_calls:
                    return BridgeDelta(role, content, tool_calls)
            return BridgeDelta()
        # 老版：wrapper 内嵌 body 字符串
        inner = obj.get("body") or ""
        if not inner:
            return BridgeDelta()
        inner_json = json.loads(inner)
        for choice in inner_json.get("choices", []):
            delta = choice.get("delta", {})
            role = delta.get("role") or ""
            content = delta.get("content") or ""
            tool_calls = delta.get("tool_calls") if isinstance(delta.get("tool_calls"), list) else None
            if role or content or tool_calls:
                return BridgeDelta(role, content, tool_calls)
    except (TypeError, json.JSONDecodeError):
        return BridgeDelta()
    return BridgeDelta()


def make_chunk(chunk_id: str, created: int, model: str, delta: dict[str, Any] | None = None, finish_reason: str | None = None) -> dict[str, Any]:
    return {"id": chunk_id, "object": "chat.completion.chunk", "created": created, "model": model, "choices": [{"index": 0, "delta": delta or {}, "finish_reason": finish_reason}]}


class ToolCallAccumulator:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def append(self, delta_calls: list[dict[str, Any]]) -> None:
        for delta in delta_calls:
            index = delta.get("index") if isinstance(delta.get("index"), int) else len(self.calls)
            while len(self.calls) <= index:
                self.calls.append({"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
            existing = self.calls[index]
            if isinstance(delta.get("id"), str):
                existing["id"] = delta["id"]
            if isinstance(delta.get("type"), str):
                existing["type"] = delta["type"]
            function = delta.get("function") or {}
            if isinstance(function.get("name"), str):
                existing["function"]["name"] = function["name"]
            if isinstance(function.get("arguments"), str):
                existing["function"]["arguments"] += function["arguments"]

    def snapshot(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self.calls)


def build_new_protocol_body(req: dict[str, Any]) -> tuple[dict[str, Any], str, bool]:
    """新版协议 body（备用路径，USE_OLD_PROTOCOL=0 时启用）：OpenAI 原生格式。"""
    model = req.get("model") or "lite"
    messages = req.get("messages") if isinstance(req.get("messages"), list) else []
    tools_enabled = bool(req.get("tools"))
    rid = str(uuid.uuid4())
    body: dict[str, Any] = {
        "model": model,
        "messages": copy.deepcopy(messages or []),
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
    if tools_enabled:
        body["tools"] = copy.deepcopy(req["tools"])
    return body, model, tools_enabled


# ---------------------------------------------------------------- 共享 HTTP 客户端
# httpx 0.28 的代理只能挂在 client 上（无按请求 proxy 参数），因此按“代理地址”
# 缓存一组 client：相同代理的账号共享连接池，直连/全局代理各自一个池。
_CLIENTS: dict[str, httpx.AsyncClient] = {}
_CLIENT_INIT_LOCK = asyncio.Lock()


def resolve_proxy(sess: SessionContext) -> str | None:
    """账号级代理优先，未启用回退全局 .env（QODER_PROXY），再回退直连。

    带账号密码时拼进 URL userinfo（httpx 代理认证只认 URL 形式），
    用户名/密码做 URL 编码，避免特殊字符破坏 URL。
    """
    if getattr(sess, "proxy_enabled", False) and (sess.proxy_url or "").strip():
        url = sess.proxy_url.strip()
        user = (sess.proxy_username or "").strip()
        pwd = sess.proxy_password or ""
        if user:
            scheme, _, rest = url.partition("://")
            if rest:
                creds = quote(user, safe="")
                if pwd:
                    creds = creds + ":" + quote(pwd, safe="")
                return f"{scheme}://{creds}@{rest}"
        return url
    return proxy_url()


async def client_for(sess: SessionContext) -> httpx.AsyncClient:
    """按账号代理设置取（或创建）共享 client。"""
    return await _client_for_proxy(resolve_proxy(sess))


async def _client_for_proxy(proxy: str | None) -> httpx.AsyncClient:
    key = proxy or ""
    client = _CLIENTS.get(key)
    if client is not None and not client.is_closed:
        return client
    async with _CLIENT_INIT_LOCK:
        client = _CLIENTS.get(key)
        if client is None or client.is_closed:
            client = httpx.AsyncClient(
                proxy=proxy or None,
                timeout=httpx.Timeout(connect=15, read=STREAM_READ_TIMEOUT, write=60, pool=60),
                limits=httpx.Limits(max_connections=HTTP_MAX_CONNECTIONS,
                                    max_keepalive_connections=HTTP_MAX_KEEPALIVE,
                                    keepalive_expiry=120.0),
                **httpx_client_kwargs(),
            )
            _CLIENTS[key] = client
        return client


async def shared_client() -> httpx.AsyncClient:
    """无账号上下文时的默认 client（全局 .env 代理或直连）。"""
    return await _client_for_proxy(proxy_url())


async def close_shared_client() -> None:
    """应用关闭时释放全部连接池（lifespan shutdown 调用）。"""
    async with _CLIENT_INIT_LOCK:
        clients = list(_CLIENTS.values())
        _CLIENTS.clear()
    for c in clients:
        if not c.is_closed:
            try:
                await c.aclose()
            except Exception:
                pass


# ---------------------------------------------------------------- 单账号并发闸
_ACCOUNT_SLOTS: dict[str, asyncio.Semaphore] = {}
_SLOTS_LOCK = threading.Lock()


def _account_semaphore(uid: str) -> asyncio.Semaphore:
    with _SLOTS_LOCK:
        sem = _ACCOUNT_SLOTS.get(uid)
        if sem is None:
            sem = asyncio.Semaphore(ACCOUNT_CONCURRENCY)
            _ACCOUNT_SLOTS[uid] = sem
        return sem


class AccountSlotBusy(RuntimeError):
    """等待账号并发槽位超时（临时性拥塞，不算账号错误，不轮换）。"""


@asynccontextmanager
async def account_slot(uid: str) -> AsyncIterator[None]:
    """限制同一账号同时在飞的上游请求数，保护上游配额/降低 402 与挂起。"""
    sem = _account_semaphore(uid)
    try:
        await asyncio.wait_for(sem.acquire(), timeout=ACCOUNT_SLOT_WAIT)
    except asyncio.TimeoutError as exc:
        raise AccountSlotBusy(
            f"Account slot busy: no free slot for {uid} within {ACCOUNT_SLOT_WAIT:.0f}s"
        ) from exc
    try:
        yield
    finally:
        sem.release()


def raise_if_error_frame(line: str, model: str, account_uid: str) -> None:
    """老版协议错误帧检测：data 包裹的 body 是 {"code":..., "message":...} 而非 choices。

    正常内容帧的 body 一定含 choices；错误帧只含 code/message。命中即抛
    UpstreamErrorFrame（账号级错误，触发轮换）。
    """
    if not line.startswith("data:"):
        return
    raw = line[5:].strip()
    if not raw or raw == "[DONE]":
        return
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return
    if not isinstance(obj, dict):
        return
    inner = obj.get("body")
    if not isinstance(inner, str):
        return
    try:
        payload = json.loads(inner)
    except json.JSONDecodeError:
        return
    if not isinstance(payload, dict) or "choices" in payload:
        return
    code = payload.get("code")
    message = payload.get("message") or payload.get("error") or ""
    if code or message:
        raise UpstreamErrorFrame(
            f"Upstream error frame: code={code} message={message} (model={model}, account={account_uid})"
        )


async def qoder_stream_lines(sess: SessionContext, body: dict[str, Any], model: str) -> AsyncIterator[str]:
    """老版协议：POST api3 agent_chat_generation，COSY 签名 + encoding.encode body + X-Model-Key。

    失败模式与兜底：
    - 非 200：抛 RuntimeError（含 HTTP 状态码，走 app.is_account_error 判定轮换）
    - 200 但 FIRST_TOKEN_TIMEOUT 内无任何字节：抛 UpstreamHangError（挂起，触发轮换）
    - 首字之后 STREAM_READ_TIMEOUT 内无数据：httpx.ReadTimeout（临时错误）
    """
    payload = encoding.encode(json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode())
    headers = bearer_headers(sess, QODER_CHAT_URL, payload, "text/event-stream",
                             extra_headers={"X-Model-Key": model, "X-Model-Source": "system"})
    client = await client_for(sess)
    async with client.stream("POST", QODER_CHAT_URL, content=payload, headers=headers) as response:
        if response.status_code != 200:
            text = await response.aread()
            raise RuntimeError(f"HTTP {response.status_code} {text.decode(errors='replace')}")
        line_iter = response.aiter_lines()
        # 首字超时：老版协议对无配额模型 HTTP 200 后无限挂起（可能先吐空行/注释行充数），
        # 只认非空、非 SSE 注释的行为"首字"。
        first: str | None = None
        deadline = time.monotonic() + FIRST_TOKEN_TIMEOUT
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    line = await asyncio.wait_for(line_iter.__anext__(), timeout=remaining)
                except StopAsyncIteration:
                    return
                stripped = (line or "").strip()
                if stripped and not stripped.startswith(":"):
                    raise_if_error_frame(line, model, sess.identity.uid)
                    first = line
                    break
        except asyncio.TimeoutError:
            first = None
        if first is None:
            raise UpstreamHangError(
                f"Upstream hang: no first token within {FIRST_TOKEN_TIMEOUT:.0f}s "
                f"(model={model}, account={sess.identity.uid})"
            )
        yield first
        async for line in line_iter:
            if line:
                raise_if_error_frame(line, model, sess.identity.uid)
                yield line


async def new_protocol_stream_lines(req: dict[str, Any], sess: SessionContext) -> AsyncIterator[str]:
    """新版协议（备用路径）：POST api2-v2.qoder.sh/model/v1/chat/completions，Bearer 直连。"""
    body, _, _ = build_new_protocol_body(req)
    ctx = (body.get("metadata") or {}).get("context") or {}
    headers = {
        "Authorization": f"Bearer {sess.identity.security_oauth_token}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "User-Agent": "qoder/1.1.16",
        "X-Request-ID": ctx.get("request_id", ""),
        "X-Session-ID": ctx.get("session_id", ""),
    }
    async with (await client_for(sess)).stream("POST", QODER_CHAT_URL_NEW, json=body, headers=headers) as response:
        if response.status_code != 200:
            text = await response.aread()
            raise RuntimeError(f"HTTP {response.status_code} {text.decode(errors='replace')}")
        async for line in response.aiter_lines():
            if line:
                yield line


async def stream_openai_response(req: dict[str, Any], sess: SessionContext) -> AsyncIterator[str]:
    if USE_OLD_PROTOCOL:
        body, model, tools_enabled = build_qoder_body(req, sess)
        lines = qoder_stream_lines(sess, body, model)
    else:
        _, model, tools_enabled = build_new_protocol_body(req)
        lines = new_protocol_stream_lines(req, sess)
    # 单账号并发闸：整个流式期间持槽（上游连接活着），防同一账号被打爆
    async with account_slot(sess.identity.uid):
        async for line in _stream_openai_chunks(lines, model, tools_enabled):
            yield line


async def _stream_openai_chunks(lines: AsyncIterator[str], model: str, tools_enabled: bool) -> AsyncIterator[str]:
    chunk_id = "chatcmpl-" + uuid.uuid4().hex[:24]
    created = int(time.time())
    tool_calls = ToolCallAccumulator()
    emitted = False
    pending = ""
    streaming_text = False
    pending_role = "assistant"

    def event(payload: dict[str, Any]) -> str:
        return f"data: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n"

    async for line in lines:
        if not line.startswith("data:"):
            continue
        delta = extract_delta(line[5:].strip())
        if delta.is_empty:
            continue
        if delta.role:
            pending_role = delta.role
        if delta.tool_calls:
            pending = "" if tools_enabled and pending.lstrip().startswith("Tool calls:") else pending
            indexed = []
            for index, call in enumerate(delta.tool_calls):
                item = copy.deepcopy(call)
                item.setdefault("index", index)
                indexed.append(item)
            tool_calls.append(indexed)
            out_delta = {"tool_calls": indexed}
            if not emitted:
                out_delta["role"] = pending_role
            emitted = True
            yield event(make_chunk(chunk_id, created, model, out_delta))
            continue
        if not delta.content:
            continue
        if not tools_enabled or streaming_text:
            out_delta = {"content": delta.content}
            if not emitted:
                out_delta["role"] = pending_role
            emitted = True
            streaming_text = True
            yield event(make_chunk(chunk_id, created, model, out_delta))
            continue
        pending += delta.content
        candidate = pending.lstrip()
        if "Tool calls:".startswith(candidate) or candidate.startswith("Tool calls:"):
            continue
        streaming_text = True
        out_delta = {"content": pending}
        if not emitted:
            out_delta["role"] = pending_role
        emitted = True
        pending = ""
        yield event(make_chunk(chunk_id, created, model, out_delta))

    parsed_calls = parse_tool_calls_text(pending) if tools_enabled else None
    if parsed_calls:
        indexed = []
        for index, call in enumerate(parsed_calls):
            item = copy.deepcopy(call)
            item.setdefault("index", index)
            indexed.append(item)
        tool_calls.append(indexed)
        yield event(make_chunk(chunk_id, created, model, {"tool_calls": indexed, "role": pending_role} if not emitted else {"tool_calls": indexed}))
    elif pending:
        yield event(make_chunk(chunk_id, created, model, {"content": pending, "role": pending_role} if not emitted else {"content": pending}))

    finish_reason = "tool_calls" if tool_calls.calls else "stop"
    yield event(make_chunk(chunk_id, created, model, {}, finish_reason))
    yield "data: [DONE]\n\n"


async def complete_openai_response(req: dict[str, Any], sess: SessionContext) -> dict[str, Any]:
    if USE_OLD_PROTOCOL:
        body, model, tools_enabled = build_qoder_body(req, sess)
        lines = qoder_stream_lines(sess, body, model)
    else:
        _, model, tools_enabled = build_new_protocol_body(req)
        lines = new_protocol_stream_lines(req, sess)
    completion_id = "chatcmpl-" + uuid.uuid4().hex[:24]
    created = int(time.time())
    full = []
    tool_calls = ToolCallAccumulator()
    async with account_slot(sess.identity.uid):
        async for line in lines:
            if not line.startswith("data:"):
                continue
            delta = extract_delta(line[5:].strip())
            if delta.content:
                full.append(delta.content)
            if delta.tool_calls:
                tool_calls.append(delta.tool_calls)
    content = "".join(full)
    fallback_tool_calls = None if tool_calls.calls or not tools_enabled else parse_tool_calls_text(content)
    message: dict[str, Any] = {"role": "assistant"}
    if fallback_tool_calls:
        message["content"] = None
        message["tool_calls"] = fallback_tool_calls
    elif not content and tool_calls.calls:
        message["content"] = None
    else:
        message["content"] = content
    if tool_calls.calls:
        message["tool_calls"] = tool_calls.snapshot()
    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls" if tool_calls.calls or fallback_tool_calls else "stop"}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }
