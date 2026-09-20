import argparse
import collections
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .auth import SessionContext, create_session, load_local_session
from .bridge import complete_openai_response, stream_openai_response
from .config import (
    load_config,
    save_config,
    list_api_keys,
    upsert_api_key,
    delete_api_key,
)
from .database import get_db
from .env import env_bool
from . import ratelimit
from .routing import pick_uid
from .accounts import (
    db_load_accounts,
    db_get_settings,
    db_set_settings,
    import_current_auth,
    get_active_session,
    rotate_next_account,
    batch_import_accounts,
    export_accounts,
    enabled_uids,
    get_session_for_uid,
    mark_account_failed,
)
from .registrar import get_registrar_status, start_registration, stop_registration
from .tokens import (
    refresh_all_account_tokens,
    refresh_one_account,
    get_account_quota,
    get_all_accounts_quota,
    start_refresh_loop,
)

if getattr(sys, "frozen", False):  # PyInstaller 单文件：资源解压到 _MEIPASS
    BASE_DIR = str(Path(sys._MEIPASS) / "qoder2api")
else:
    BASE_DIR = os.path.dirname(__file__)
INDEX_HTML = Path(BASE_DIR) / "static" / "index.html"
CONSOLE_HTML = Path(BASE_DIR) / "static" / "console.html"
DOCS_HTML = Path(BASE_DIR) / "static" / "docs.html"

app = FastAPI(title="qoder2api-python")
app.mount("/assets", StaticFiles(directory=os.path.join(BASE_DIR, "static", "assets")), name="assets")

_session: SessionContext | None = None
_local_auth_error: str | None = None

logs_queue = collections.deque(maxlen=150)


def add_log(msg: str, level: str = "INFO") -> None:
    timestamp = datetime.now().strftime("%H:%M:%S")
    formatted = f"[{timestamp}] [{level}] {msg}"
    logs_queue.append(formatted)
    print(formatted)


# Add initial logs
add_log("Qoder2API Python Bridge initialized.")



def check_gateway_token(x_gateway_token: str | None = Header(default=None)):
    config = load_config()
    gateway_token = config.get("gateway_token", "admin")
    if not x_gateway_token or x_gateway_token != gateway_token:
        raise HTTPException(status_code=401, detail="Unauthorized gateway access")


@app.post("/ui/verify")
async def verify_gateway(payload: dict[str, Any]) -> dict[str, Any]:
    token = payload.get("token", "").strip()
    config = load_config()
    if token == config.get("gateway_token", "admin"):
        return {"status": "ok"}
    raise HTTPException(status_code=401, detail="Invalid Gateway Token")


async def get_session() -> SessionContext:
    global _local_auth_error
    data = db_load_accounts()
    if not data["accounts"]:
        # Try importing environment PAT if available
        pat = os.getenv("QODER_PAT", "").strip()
        if pat:
            add_log("No accounts stored. Importing QODER_PAT from environment...")
            try:
                sess = await create_session(pat)
                with get_db() as conn:
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO accounts (
                            uid, name, user_type, security_oauth_token, refresh_token, machine_id,
                            enabled, last_status, last_error
                        ) VALUES (?, ?, ?, ?, ?, ?, 1, 'ok', NULL)
                        """,
                        (sess.identity.uid, sess.identity.name or "Environment PAT", sess.identity.user_type,
                         sess.identity.security_oauth_token, sess.identity.refresh_token, sess.machine_id)
                    )
                db_set_settings("active_uid", sess.identity.uid)
                add_log(f"Imported environment PAT as account: {sess.identity.name}")
                _local_auth_error = None
            except Exception as exc:
                add_log(f"Failed to import environment PAT: {exc}", "ERROR")

        data = db_load_accounts()
        if not data["accounts"]:
            add_log("No accounts stored. Attempting to auto-import current local Qoder auth session...")
            try:
                await import_current_auth()
                add_log("Auto-imported current local Qoder session successfully.")
                _local_auth_error = None
            except Exception as exc:
                _local_auth_error = str(exc)
                add_log(f"Auto-import of local session failed: {exc}", "WARNING")

    try:
        return get_active_session()
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"No active session available: {exc}. Please configure/import an account first."
        )


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    if not env_bool("QODER_ENABLE_LANDING", True):
        raise HTTPException(status_code=404, detail="Landing page is disabled")
    return HTMLResponse(INDEX_HTML.read_text(encoding="utf-8"))


@app.get("/console", response_class=HTMLResponse)
async def console() -> HTMLResponse:
    return HTMLResponse(CONSOLE_HTML.read_text(encoding="utf-8"))


@app.get("/documents", response_class=HTMLResponse)
async def documents() -> HTMLResponse:
    if not env_bool("QODER_ENABLE_DOCUMENTS", True):
        raise HTTPException(status_code=404, detail="Documents page is disabled")
    return HTMLResponse(DOCS_HTML.read_text(encoding="utf-8"))


@app.get("/ui/status")
async def status(verify: None = Depends(check_gateway_token)) -> dict[str, Any]:
    global _local_auth_error
    try:
        await get_session()
    except Exception:
        pass

    data = db_load_accounts()
    active_uid = data.get("active_uid")
    active_acc = None
    for acc in data["accounts"]:
        if acc["uid"] == active_uid:
            active_acc = acc
            break

    if active_acc is not None:
        return {
            "ready": True,
            "mode": "accounts",
            "username": active_acc["name"],
            "uid": active_acc["uid"],
            "user_type": active_acc["user_type"],
            "error": None,
            "accounts_count": len(data["accounts"])
        }
    return {
        "ready": False,
        "mode": "none",
        "username": None,
        "uid": None,
        "user_type": None,
        "error": _local_auth_error,
        "accounts_count": len(data["accounts"])
    }


@app.get("/ui/accounts")
async def get_accounts(verify: None = Depends(check_gateway_token)) -> dict[str, Any]:
    return db_load_accounts()


@app.get("/ui/accounts/export")
async def export_accounts_endpoint(
    download: int = 1,
    include_secrets: int = 1,
    verify: None = Depends(check_gateway_token),
) -> Response:
    """导出账号池：注册机 accounts.json 兼容的数组，可直接被 /ui/accounts/batch-import 回灌。

    download=0 返回内联 JSON；include_secrets=0 剔除 password / token / refresh_token。
    """
    records = export_accounts(include_secrets=bool(include_secrets))
    body = json.dumps(records, ensure_ascii=False, indent=2)
    headers: dict[str, str] = {}
    if download:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        headers["Content-Disposition"] = (
            f'attachment; filename="qoder-accounts-{stamp}.json"')
    add_log(f"Exported {len(records)} accounts (include_secrets={bool(include_secrets)})")
    return Response(content=body, media_type="application/json", headers=headers)


@app.post("/ui/accounts/import")
async def import_account(verify: None = Depends(check_gateway_token)) -> dict[str, Any]:
    try:
        acc = await import_current_auth()
        add_log(f"Imported local Qoder session account: {acc['name']}")
        return {"status": "ok", "account": acc}
    except Exception as exc:
        add_log(f"Failed to import local session account: {exc}", "ERROR")
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/ui/accounts/batch-import")
async def batch_import(payload: dict[str, Any], verify: None = Depends(check_gateway_token)) -> dict[str, Any]:
    """批量导入注册机导出的 JSON：{"accounts": [{user_id, token, refresh_token, ...}]}。"""
    records = payload.get("accounts") or payload.get("records") or []
    if not isinstance(records, list) or not records:
        raise HTTPException(status_code=400, detail="accounts 数组为空")
    result = batch_import_accounts(records)
    add_log(f"Batch imported {result['imported']} accounts (skipped {result['skipped']})")
    return {"status": "ok", **result}


@app.post("/ui/accounts/select")
async def select_account(payload: dict[str, Any], verify: None = Depends(check_gateway_token)) -> dict[str, Any]:
    uid = payload.get("uid")
    if not uid:
        raise HTTPException(status_code=400, detail="uid is required")
    with get_db() as conn:
        res = conn.execute("SELECT uid FROM accounts WHERE uid = ?", (uid,)).fetchone()
        if not res:
            raise HTTPException(status_code=404, detail="Account not found")
    db_set_settings("active_uid", uid)
    add_log(f"Selected active account UID: {uid}")
    return {"status": "ok"}


@app.post("/ui/accounts/toggle")
async def toggle_account(payload: dict[str, Any], verify: None = Depends(check_gateway_token)) -> dict[str, Any]:
    uid = payload.get("uid")
    enabled = bool(payload.get("enabled", True))
    if not uid:
        raise HTTPException(status_code=400, detail="uid is required")
    enabled_val = 1 if enabled else 0
    with get_db() as conn:
        res = conn.execute("UPDATE accounts SET enabled = ? WHERE uid = ?", (enabled_val, uid))
        if res.rowcount == 0:
            raise HTTPException(status_code=404, detail="Account not found")
    add_log(f"Account toggle enabled={enabled} for UID: {uid}")
    return {"status": "ok"}


@app.post("/ui/accounts/refresh-tokens")
async def refresh_account_tokens(verify: None = Depends(check_gateway_token)) -> dict[str, Any]:
    """手动触发：刷新所有账号的 token（drt- → deviceToken/refresh）。"""
    result = refresh_all_account_tokens()
    add_log(f"Token refresh: ok={result['ok']} failed={result['failed']} total={result['total']}")
    return {"status": "ok", **result}


@app.get("/ui/accounts/quota")
async def accounts_quota(verify: None = Depends(check_gateway_token)) -> dict[str, Any]:
    """查看所有启用账号的限额（GET /api/v2/quota/usage）。"""
    return get_all_accounts_quota()


@app.delete("/ui/accounts/{uid}")
async def delete_account(uid: str, verify: None = Depends(check_gateway_token)) -> dict[str, Any]:
    with get_db() as conn:
        res = conn.execute("DELETE FROM accounts WHERE uid = ?", (uid,))
        if res.rowcount == 0:
            raise HTTPException(status_code=404, detail="Account not found")
            
    active_uid = db_get_settings("active_uid")
    if active_uid == uid:
        data = db_load_accounts()
        new_active = data["accounts"][0]["uid"] if data["accounts"] else None
        if new_active:
            db_set_settings("active_uid", new_active)
        else:
            with get_db() as conn:
                conn.execute("DELETE FROM settings WHERE key = 'active_uid'")
    add_log(f"Deleted account UID: {uid}")
    return {"status": "ok"}


@app.get("/ui/logs")
async def get_logs(verify: None = Depends(check_gateway_token)) -> list[str]:
    return list(logs_queue)


@app.post("/ui/registrar/start")
async def registrar_start(payload: dict[str, Any] | None = None, verify: None = Depends(check_gateway_token)) -> dict[str, Any]:
    """启动注册机（无限循环：parents 个母线程 × 每批 3 个子任务，直到调用 stop）。

    body 可选：{"parents": 2}  —— 母线程数（1-6），每母线程 3 子任务并发。
    """
    payload = payload or {}
    try:
        parents = int(payload.get("parents", 2))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="parents 参数无效")
    return start_registration(parents=parents)


@app.post("/ui/registrar/stop")
async def registrar_stop(verify: None = Depends(check_gateway_token)) -> dict[str, Any]:
    """请求停止：当前批次完成后停止，返回本次注册统计。"""
    return stop_registration()


@app.get("/ui/registrar/status")
async def registrar_status(verify: None = Depends(check_gateway_token)) -> dict[str, Any]:
    """查询注册机任务状态（stage / logs / result）。"""
    return get_registrar_status()


@app.get("/ui/config")
async def get_ui_config(verify: None = Depends(check_gateway_token)) -> dict[str, Any]:
    return load_config()


@app.post("/ui/config")
async def post_ui_config(payload: dict[str, Any], verify: None = Depends(check_gateway_token)) -> dict[str, Any]:
    save_config(payload)
    add_log("API Key configuration updated.")
    return {"status": "ok"}


@app.get("/ui/keys")
async def list_keys(verify: None = Depends(check_gateway_token)) -> dict[str, Any]:
    """列出 API Key（含名称/路由策略/限额/实时用量）。"""
    keys = list_api_keys()
    for k in keys:
        k.update(ratelimit.usage(k["api_key"]))
    return {"keys": keys, "auth_required": bool(load_config().get("auth_required"))}


@app.post("/ui/keys")
async def save_key(payload: dict[str, Any], verify: None = Depends(check_gateway_token)) -> dict[str, Any]:
    """新增/更新一条 API Key。

    字段：api_key（必填）、name、strategy（1=填充/固定 2=轮询）、
    rpm_limit、concurrency_limit（0=不限）、enabled
    """
    try:
        rec = upsert_api_key(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    add_log(f"API Key saved: {rec['api_key'][:8]}... name={rec['name']!r} "
            f"strategy={rec['strategy']} rpm={rec['rpm_limit']} "
            f"conc={rec['concurrency_limit']} enabled={rec['enabled']}")
    rec.update(ratelimit.usage(rec["api_key"]))
    return {"status": "ok", "key": rec}


@app.delete("/ui/keys/{api_key}")
async def remove_key(api_key: str, verify: None = Depends(check_gateway_token)) -> dict[str, Any]:
    if not delete_api_key(api_key):
        raise HTTPException(status_code=404, detail="API Key not found")
    add_log(f"API Key deleted: {api_key[:8]}...")
    return {"status": "ok"}


@app.post("/ui/session")
async def set_session(payload: dict[str, Any], verify: None = Depends(check_gateway_token)) -> dict[str, Any]:
    global _local_auth_error
    pat = str(payload.get("pat") or os.getenv("QODER_PAT", "")).strip()
    if not pat:
        raise HTTPException(status_code=400, detail="PAT is required")
    try:
        add_log("Attempting to save session from PAT...")
        sess = await create_session(pat)
        
        # Insert or update in SQLite
        with get_db() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO accounts (
                    uid, name, user_type, security_oauth_token, refresh_token, machine_id,
                    enabled, last_status, last_error
                ) VALUES (?, ?, ?, ?, ?, ?, 1, 'ok', ?)
                """,
                (sess.identity.uid, sess.identity.name or "PAT Account", sess.identity.user_type,
                 sess.identity.security_oauth_token, sess.identity.refresh_token, sess.machine_id, None)
            )
            
        db_set_settings("active_uid", sess.identity.uid)
        
        add_log(f"Session saved from PAT. User: {sess.identity.name}")
        _local_auth_error = None
        return {"ready": True, "id": sess.identity.uid, "name": sess.identity.name, "user_type": sess.identity.user_type}
    except Exception as exc:
        msg = f"Failed to authenticate with provided PAT: {exc}"
        add_log(msg, "ERROR")
        raise HTTPException(status_code=502, detail=msg) from exc


def is_quota_error(exc: Exception) -> bool:
    """判断是否为 quota/限流类错误（429 / quota / rate limit）。
    这类错误需先查询真实限额确认，不能直接跳过账户。"""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429
    if isinstance(exc, RuntimeError):
        msg = str(exc).lower()
        return any(k in msg for k in ("http 429", "quota", "rate limit", "insufficient"))
    return False


def is_account_error(exc: Exception) -> bool:
    """判断是否'账号级'错误（token 无效/限额/服务端拒绝）。只有这类才应跳过账户。

    网络/流中断/超时（如 httpx.ReadError 的 incomplete chunk read）是临时性问题，
    换账户也无效，不应触发 rotate。
    """
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (401, 403, 429)
    if isinstance(exc, httpx.HTTPError):
        return False  # 连接/超时/读错误等网络问题
    if isinstance(exc, RuntimeError):
        msg = str(exc).lower()
        if any(code in msg for code in ("http 401", "http 403", "http 429")):
            return True
        for kw in ("unauthorized", "invalid token", "quota", "rate limit",
                   "insufficient", "personal token", "credit"):
            if kw in msg:
                return True
    return False


async def _pick_session(key_cfg: dict[str, Any] | None, model: str, tried: set[str]):
    """按 API Key 的路由策略挑选本次请求使用的账号。

    - 无 key（或未开鉴权且未带 key）：沿用原有 active 账号逻辑
    - 有 key：按 strategy 从「已启用账号」中挑选；tried 里的账号会被跳过（失败重试顺延）
    """
    if not key_cfg:
        return await get_session()
    uids = enabled_uids()
    if not uids:
        return await get_session()
    uid = pick_uid(key_cfg["api_key"], model, int(key_cfg.get("strategy") or 1), uids, tried)
    if not uid:
        raise ValueError("No available account left for this API key.")
    return get_session_for_uid(uid)


@app.post("/v1/chat/completions")
async def chat_completions(payload: dict[str, Any], authorization: str | None = Header(default=None)):
    config = load_config()
    auth_required = bool(config.get("auth_required", False))

    # ---- 解析调用方 API Key（未开鉴权时也允许带 key，以便启用策略/限流）----
    incoming_key = ""
    if authorization and authorization.startswith("Bearer "):
        incoming_key = authorization[len("Bearer "):].strip()
    key_cfg: dict[str, Any] | None = None
    for _k in config.get("api_keys", []):
        if _k.get("api_key") and _k.get("api_key") == incoming_key and _k.get("enabled"):
            key_cfg = _k
            break
    if auth_required and not key_cfg:
        add_log("Access denied: Invalid or missing API Key in request header.", "WARNING")
        raise HTTPException(status_code=401, detail="Invalid or missing API Key")

    # ---- 限流：RPM + 并发（0=不限）。并发名额必须在请求/流结束后释放 ----
    released = {"done": False}

    def _release() -> None:
        if key_cfg and not released["done"]:
            released["done"] = True
            ratelimit.release(key_cfg["api_key"])

    if key_cfg:
        _ok, _reason, _retry_after = ratelimit.acquire(
            key_cfg["api_key"], key_cfg.get("rpm_limit", 0),
            key_cfg.get("concurrency_limit", 0))
        if not _ok:
            add_log(f"Rate limited (key={key_cfg['api_key'][:8]}...): {_reason}", "WARNING")
            raise HTTPException(status_code=429, detail=_reason,
                                headers={"Retry-After": str(int(_retry_after) + 1)})

    model = payload.get("model", "lite")
    stream = bool(payload.get("stream", False))
    messages_count = len(payload.get("messages", []))
    add_log(f"Incoming completion request: model={model}, stream={stream}, messages={messages_count}"
            + (f", key={key_cfg['api_key'][:8]}... strategy={key_cfg['strategy']}"
               f" rpm={key_cfg.get('rpm_limit')} conc={key_cfg.get('concurrency_limit')}"
               if key_cfg else ", no-key"))

    accounts_data = db_load_accounts()
    enabled_count = sum(1 for acc in accounts_data["accounts"] if acc.get("enabled", True))
    max_retries = max(1, enabled_count)
    tried: set[str] = set()
    handed_off = {"done": False}

    async def _releasing_stream(inner):
        """流式响应结束后释放并发名额。"""
        try:
            async for chunk in inner:
                yield chunk
        finally:
            _release()

    try:
        for attempt in range(max_retries):
            session_obj = None
            try:
                session_obj = await _pick_session(key_cfg, model, tried)
                tried.add(session_obj.identity.uid)
                add_log(f"Request routing via account: {session_obj.identity.name} "
                        f"({session_obj.identity.uid})")
                if stream:
                    gen = stream_openai_response(payload, session_obj)
                    try:
                        first_item = await gen.__anext__()
                    except StopAsyncIteration:
                        first_item = None

                    async def stream_success_wrapper(first, g):
                        if first is not None:
                            yield first
                        async for chunk in g:
                            yield chunk

                    add_log(f"Streaming response initiated (Attempt {attempt+1}/{max_retries}).")
                    handed_off["done"] = True
                    return StreamingResponse(
                        _releasing_stream(stream_success_wrapper(first_item, gen)),
                        media_type="text/event-stream",
                        headers={"Cache-Control": "no-cache"}
                    )
                else:
                    add_log(f"Generating full completion response (Attempt {attempt+1}/{max_retries})...")
                    resp = await complete_openai_response(payload, session_obj)
                    add_log("Completion request finished successfully.")
                    return resp
            except Exception as exc:
                current_uid = session_obj.identity.uid if session_obj is not None else "unknown"
                if is_account_error(exc):
                    if is_quota_error(exc):
                        # quota 类错误：先发一次请求确认是否真正 exceeded，而不是直接跳过
                        q = get_account_quota(current_uid)
                        if q.get("ok"):
                            quota = q["quota"]
                            truly_exceeded = bool(quota.get("isQuotaExceeded")) or (quota.get("userQuota") or {}).get("remaining", 1) <= 0
                            if not truly_exceeded:
                                add_log(f"Quota check on {current_uid}: NOT exceeded (remaining={quota.get('userQuota', {}).get('remaining')}), not rotating.", "WARNING")
                                raise HTTPException(status_code=502, detail=f"{exc}")
                            add_log(f"Quota confirmed exceeded for {current_uid}: {exc}. Rotating...", "WARNING")
                        else:
                            # 限额查询失败：无法确认，保守不跳过账户
                            add_log(f"Quota check failed for {current_uid} ({q.get('error')}), not rotating.", "WARNING")
                            raise HTTPException(status_code=502, detail=f"{exc}")
                    else:
                        add_log(f"Account-level error on {current_uid}: {exc}. Rotating to next account...", "WARNING")
                    try:
                        if key_cfg:
                            # 按 key 路由：只标记失败，不改动全局 active_uid
                            mark_account_failed(current_uid, str(exc))
                        else:
                            rotate_next_account(current_uid, str(exc))
                    except Exception as e:
                        add_log(f"Failed to rotate account: {e}", "ERROR")
                        raise HTTPException(status_code=502, detail=f"Request failed and no other account is available. Error: {exc}")
                else:
                    add_log(f"Transient error on account {current_uid}: {exc}. Not rotating account.", "WARNING")
                    raise HTTPException(status_code=502, detail=str(exc))

        raise HTTPException(status_code=502, detail="Request failed on all available accounts.")
    finally:
        if not handed_off["done"]:
            _release()


def main() -> None:
    import uvicorn

    start_refresh_loop()  # 启动 token 定时刷新线程（每 6 小时）

    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=os.getenv("QODER_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("QODER_PORT", "5050")))
    args = parser.parse_args()
    kwargs = {}
    if getattr(sys, "frozen", False):
        # 无控制台打包：sys.stdout 可能为 None，uvicorn 默认 dictConfig 的
        # 彩色 Formatter 会调 sys.stdout.isatty() 崩溃，禁用其日志配置。
        kwargs["log_config"] = None
        kwargs["log_level"] = "info"
    uvicorn.run(app, host=args.host, port=args.port, reload=False, **kwargs)

if __name__ == "__main__":
    main()
