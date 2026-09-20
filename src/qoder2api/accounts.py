import copy
import os
import threading
import time
import uuid
from dataclasses import replace
from typing import Any

from .auth import (
    AuthIdentity,
    SessionContext,
    load_local_session,
    new_session,
    new_machine,
    fetch_user_status
)
from .database import get_db


# ---------------------------------------------------------------------------
# 会话缓存：get_session_for_uid 每次都要同步读 sqlite + RSA/AES 构造 SessionContext，
# 高并发下这是事件循环上的同步阻塞与 CPU 开销。按 uid 缓存 TTL 秒。
# token 刷新（tokens.py）写库后调用 invalidate_session_cache(uid) 失效。
# ---------------------------------------------------------------------------
SESSION_CACHE_TTL = float(os.getenv("QODER_SESSION_CACHE_TTL", "60"))
_SESSION_CACHE: dict[str, tuple[float, SessionContext]] = {}
_SESSION_CACHE_LOCK = threading.Lock()


def invalidate_session_cache(uid: str | None = None) -> None:
    """失效会话缓存：传 uid 只失效该账号，否则全清（token 刷新后调用）。"""
    with _SESSION_CACHE_LOCK:
        if uid is None:
            _SESSION_CACHE.clear()
        else:
            _SESSION_CACHE.pop(uid, None)


def get_session_for_uid_cached(uid: str) -> SessionContext:
    """带 TTL 的 get_session_for_uid；缓存未命中时才走数据库 + 签名构造。"""
    now = time.monotonic()
    with _SESSION_CACHE_LOCK:
        hit = _SESSION_CACHE.get(uid)
        if hit is not None and now - hit[0] < SESSION_CACHE_TTL:
            return hit[1]
    sess = get_session_for_uid(uid)
    with _SESSION_CACHE_LOCK:
        _SESSION_CACHE[uid] = (time.monotonic(), sess)
    return sess


def db_get_settings(key: str, default: str | None = None) -> str | None:
    with get_db() as conn:
        res = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return res[0] if res else default


def db_set_settings(key: str, value: str) -> None:
    with get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, str(value))
        )


def db_load_accounts() -> dict[str, Any]:
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM accounts").fetchall()
        accounts = []
        for r in rows:
            account = dict(r)
            account.pop("security_oauth_token", None)
            account.pop("refresh_token", None)
            account.pop("machine_id", None)
            # 密码已落库，但默认不随接口下发（避免明文经 HTTP/前端日志外泄）；
            # 需要展示时改用 /ui/accounts?with_secrets=1 或直接查库
            account.pop("password", None)
            # 代理密码同样不下发，只回“是否已设置”标志；用户名可回显便于编辑
            account["proxy_password_set"] = bool(account.pop("proxy_password", None))
            accounts.append(account)
        active_uid = db_get_settings("active_uid")
        return {"accounts": accounts, "active_uid": active_uid}


def set_account_proxy(uid: str, *, enabled: bool, url: str, username: str,
                      password: str | None) -> dict[str, Any]:
    """设置账号级代理。password 为 None/空串表示保留原密码不清空。

    返回更新后的（脱敏）账号代理配置。
    """
    enabled_int = 1 if enabled else 0
    url = (url or "").strip()
    username = (username or "").strip()
    with get_db() as conn:
        row = conn.execute(
            "SELECT proxy_password FROM accounts WHERE uid = ?", (uid,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Account {uid} not found")
        keep_pwd = row[0] or ""
        new_pwd = keep_pwd if password is None or password == "" else password
        conn.execute(
            "UPDATE accounts SET proxy_enabled = ?, proxy_url = ?, proxy_username = ?, "
            "proxy_password = ? WHERE uid = ?",
            (enabled_int, url, username, new_pwd, uid),
        )
        after = conn.execute(
            "SELECT proxy_enabled, proxy_url, proxy_username, proxy_password FROM accounts WHERE uid = ?",
            (uid,),
        ).fetchone()
    invalidate_session_cache(uid)
    return {
        "uid": uid,
        "proxy_enabled": bool(after[0]),
        "proxy_url": after[1] or "",
        "proxy_username": after[2] or "",
        "proxy_password_set": bool(after[3]),
    }


async def import_current_auth() -> dict[str, Any]:
    """Decrypts current local auth files, queries quota status, and saves to SQLite."""
    sess = load_local_session()
    
    # Query current user quota and metadata from Qoder backend
    quota_val = 0
    is_exceeded = 0
    plan_val = "PLAN_TIER_PRO_TRIAL"
    user_tag_val = "Pro Trial"
    next_reset = None
    
    try:
        status_data = await fetch_user_status(
            sess.identity.uid,
            sess.machine_id,
            sess.machine_token,
            sess.machine_type
        )
        quota_val = status_data.get("quota", 0)
        is_exceeded = 1 if status_data.get("isQuotaExceeded", False) else 0
        plan_val = status_data.get("plan", "PLAN_TIER_PRO_TRIAL")
        user_tag_val = status_data.get("userTag", "Pro Trial")
        next_reset = status_data.get("nextResetAt")
    except Exception as e:
        # Fallback if network call fails
        print(f"Network error querying Qoder status: {e}")

    uid = sess.identity.uid
    name = sess.identity.name or "Unnamed"

    with get_db() as conn:
        # Check if already exists to keep enabled state
        existing = conn.execute("SELECT enabled FROM accounts WHERE uid = ?", (uid,)).fetchone()
        enabled = existing[0] if existing else 1

        conn.execute(
            """
            INSERT OR REPLACE INTO accounts (
                uid, name, user_type, security_oauth_token, refresh_token, machine_id,
                enabled, last_status, last_error, quota, is_quota_exceeded, plan,
                user_tag, next_reset_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uid, name, sess.identity.user_type, sess.identity.security_oauth_token,
                sess.identity.refresh_token, sess.machine_id, enabled, "ok", None,
                quota_val, is_exceeded, plan_val, user_tag_val, next_reset
            )
        )

    # Set as active if none set
    active_uid = db_get_settings("active_uid")
    if not active_uid:
        db_set_settings("active_uid", uid)

    return {
        "uid": uid,
        "name": name,
        "user_type": sess.identity.user_type,
        "enabled": bool(enabled),
        "last_status": "ok",
        "quota": quota_val,
        "is_quota_exceeded": bool(is_exceeded),
        "plan": plan_val,
        "user_tag": user_tag_val,
        "next_reset_at": next_reset
    }


def export_accounts(include_secrets: bool = True) -> list[dict]:
    """导出账号池为「注册机 accounts.json」兼容的数组，可被 /ui/accounts/batch-import 原样回灌。

    include_secrets=False 时剔除 password / token / refresh_token / machine_id，
    只保留可对外分享的元数据。
    """
    exported_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM accounts ORDER BY rowid").fetchall()
    out: list[dict] = []
    for r in rows:
        d = dict(r)
        rec: dict[str, Any] = {
            "email": d.get("email"),
            "name": d.get("name"),
            "user_id": d.get("uid"),
            "expires_at": d.get("token_expires_at"),
            "enabled": d.get("enabled"),
            "plan": d.get("plan"),
            "user_tag": d.get("user_tag"),
            "exported_at": exported_at,
        }
        if include_secrets:
            rec["password"] = d.get("password")
            rec["token"] = d.get("security_oauth_token")
            rec["refresh_token"] = d.get("refresh_token")
            rec["machine_id"] = d.get("machine_id")
        out.append(rec)
    return out


def batch_import_accounts(records: list[dict]) -> dict:
    """批量导入账号（来自注册机导出的 JSON）。

    每条记录字段：email/password/name/user_id/token/refresh_token/expires_at/...
    返回 {"imported": n, "skipped": m}。
    """
    imported = 0
    skipped = 0
    with get_db() as conn:
        for rec in records:
            uid = str(rec.get("user_id") or "").strip()
            token = str(rec.get("token") or rec.get("security_oauth_token") or "").strip()
            if not uid and not token:
                skipped += 1
                continue
            if not uid:
                # 无 user_id 时用 token 前 12 位兜底主键
                uid = "tok_" + token[:24]
            existing = conn.execute(
                "SELECT enabled, email, password, machine_id FROM accounts WHERE uid = ?", (uid,)
            ).fetchone()
            enabled = existing["enabled"] if existing else 1
            # 记录未带这些字段时保留库内旧值：INSERT OR REPLACE 是整行覆盖，
            # 不带就会把已落库的 email/password/machine_id 清空。
            email = str(rec.get("email") or "").strip() or (
                existing["email"] if existing else None)
            password = str(rec.get("password") or "").strip() or (
                existing["password"] if existing else None)
            machine_id = str(rec.get("machine_id") or "").strip() or (
                existing["machine_id"] if existing else str(uuid.uuid4()))
            conn.execute(
                """
                INSERT OR REPLACE INTO accounts (
                    uid, name, user_type, email, password,
                    security_oauth_token, refresh_token, machine_id,
                    enabled, last_status, last_error, quota, is_quota_exceeded, plan, user_tag, next_reset_at, token_expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'ok', NULL, 0, 0, 'PLAN_TIER_PRO_TRIAL', 'Pro Trial', NULL, ?)
                """,
                (
                    uid,
                    str(rec.get("name") or rec.get("email") or "Imported"),
                    "personal_standard",
                    email,
                    password,
                    token,
                    str(rec.get("refresh_token") or ""),
                    machine_id,
                    enabled,
                    str(rec.get("expires_at") or ""),
                ),
            )
            imported += 1
    # active_uid 的兜底必须放在写事务之外：在事务内再开库写会争锁
    # （实测 sqlite3.OperationalError: database is locked，busy_timeout 30s 后放弃）
    if not db_get_settings("active_uid"):
        with get_db() as conn:
            active = conn.execute(
                "SELECT uid FROM accounts WHERE enabled = 1 LIMIT 1").fetchone()
        if active:
            db_set_settings("active_uid", active["uid"])
    return {"imported": imported, "skipped": skipped}


def get_active_session() -> SessionContext:
    """Gets the session for the active account from database."""
    active_uid = db_get_settings("active_uid")
    
    account = None
    with get_db() as conn:
        if active_uid:
            res = conn.execute("SELECT * FROM accounts WHERE uid = ? AND enabled = 1", (active_uid,)).fetchone()
            if res:
                account = dict(res)
        
        if not account:
            # Fallback to first enabled account
            res = conn.execute("SELECT * FROM accounts WHERE enabled = 1 LIMIT 1").fetchone()
            if res:
                account = dict(res)
                db_set_settings("active_uid", account["uid"])

    if not account:
        raise ValueError("No active or enabled accounts found in database. Please import or configure an account.")

    identity = AuthIdentity(
        name=account["name"],
        aid=account["uid"],
        uid=account["uid"],
        yx_uid="",
        organization_id="",
        organization_name="",
        user_type=account["user_type"],
        security_oauth_token=account["security_oauth_token"],
        refresh_token=account["refresh_token"]
    )
    
    _, machine_token, machine_type = new_machine()
    return new_session(
        identity,
        account["machine_id"],
        machine_token,
        machine_type
    )


def rotate_next_account(failed_uid: str, error_msg: str) -> SessionContext:
    """Marks failed account in database, rotates to the next enabled, and returns it."""
    with get_db() as conn:
        conn.execute(
            "UPDATE accounts SET last_status = 'failed', last_error = ? WHERE uid = ?",
            (error_msg, failed_uid)
        )
        
        # Get all enabled accounts
        rows = conn.execute("SELECT * FROM accounts WHERE enabled = 1").fetchall()
        
    enabled_accounts = [dict(r) for r in rows]
    if not enabled_accounts:
        raise ValueError("All enabled accounts have failed or no enabled accounts exist.")

    # Find next cyclic account
    next_acc = None
    try:
        failed_idx = next(i for i, acc in enumerate(enabled_accounts) if acc["uid"] == failed_uid)
        next_acc = enabled_accounts[(failed_idx + 1) % len(enabled_accounts)]
    except StopIteration:
        next_acc = enabled_accounts[0]

    db_set_settings("active_uid", next_acc["uid"])
    
    identity = AuthIdentity(
        name=next_acc["name"],
        aid=next_acc["uid"],
        uid=next_acc["uid"],
        yx_uid="",
        organization_id="",
        organization_name="",
        user_type=next_acc["user_type"],
        security_oauth_token=next_acc["security_oauth_token"],
        refresh_token=next_acc["refresh_token"]
    )
    _, machine_token, machine_type = new_machine()
    return new_session(
        identity,
        next_acc["machine_id"],
        machine_token,
        machine_type
    )


# ---------------------------------------------------------------------------
# 按 key 路由所需的辅助（不改全局 active_uid）
# ---------------------------------------------------------------------------
def _session_from_row(account: dict) -> SessionContext:
    """由 accounts 表的一行构造会话。"""
    identity = AuthIdentity(
        name=account["name"],
        aid=account["uid"],
        uid=account["uid"],
        yx_uid="",
        organization_id="",
        organization_name="",
        user_type=account["user_type"],
        security_oauth_token=account["security_oauth_token"],
        refresh_token=account["refresh_token"],
    )
    _, machine_token, machine_type = new_machine()
    sess = new_session(identity, account["machine_id"], machine_token, machine_type)
    # 挂上账号级代理配置（frozen dataclass，用 replace 复制）
    return replace(
        sess,
        proxy_enabled=bool(account.get("proxy_enabled")),
        proxy_url=account.get("proxy_url") or "",
        proxy_username=account.get("proxy_username") or "",
        proxy_password=account.get("proxy_password") or "",
    )


def enabled_uids() -> list[str]:
    """已启用账号的 uid（稳定排序，供路由 hash 取模 / 轮询取用）。"""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT uid FROM accounts WHERE enabled = 1 ORDER BY uid").fetchall()
    return [r[0] for r in rows]


def get_session_for_uid(uid: str) -> SessionContext:
    """按 uid 取会话；账号不存在或被停用则抛错。"""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM accounts WHERE uid = ? AND enabled = 1", (uid,)).fetchone()
    if not row:
        raise ValueError(f"Account {uid} not found or disabled.")
    return _session_from_row(dict(row))


def mark_account_failed(uid: str, error_msg: str) -> None:
    """只记录失败状态，不改变全局 active_uid（按 key 路由时使用）。"""
    with get_db() as conn:
        conn.execute(
            "UPDATE accounts SET last_status = 'failed', last_error = ? WHERE uid = ?",
            (error_msg, uid))
