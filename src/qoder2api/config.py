from typing import Any
import time

from .database import get_db
from .env import admin_password

_CFG_CACHE: dict[str, Any] | None = None
_CFG_TS = 0.0
_CFG_TTL = 5.0

# API Key 默认值：strategy 1=填充(固定) / 2=轮询；limit 0=不限
KEY_FIELDS = ("api_key", "name", "strategy", "rpm_limit", "concurrency_limit",
              "enabled", "created_at")


def _row_to_key(row: Any) -> dict[str, Any]:
    d = dict(row)
    enabled = d.get("enabled")
    return {
        "api_key": d.get("api_key") or "",
        "name": d.get("name") or "",
        "strategy": int(d.get("strategy") or 1),
        "rpm_limit": int(d.get("rpm_limit") or 0),
        "concurrency_limit": int(d.get("concurrency_limit") or 0),
        "enabled": 1 if enabled is None else int(enabled),
        "created_at": d.get("created_at") or "",
    }


def list_api_keys() -> list[dict[str, Any]]:
    """列出所有 API Key（含名称/策略/限额），按创建时间排序。"""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT api_key, name, strategy, rpm_limit, concurrency_limit, enabled, created_at "
            "FROM allowed_keys ORDER BY created_at, api_key").fetchall()
    return [_row_to_key(r) for r in rows]


def get_api_key(api_key: str) -> dict[str, Any] | None:
    if not api_key:
        return None
    with get_db() as conn:
        row = conn.execute(
            "SELECT api_key, name, strategy, rpm_limit, concurrency_limit, enabled, created_at "
            "FROM allowed_keys WHERE api_key = ?", (api_key,)).fetchone()
    return _row_to_key(row) if row else None


def upsert_api_key(rec: dict[str, Any]) -> dict[str, Any]:
    """新增或更新一条 API Key；未传的字段沿用旧值（新建则用默认值）。

    strategy: 1=填充(同 key+模型固定账号) / 2=轮询(每次请求依次下一个)
    rpm_limit / concurrency_limit: 0 表示不限
    """
    key = str(rec.get("api_key") or "").strip()
    if not key:
        raise ValueError("api_key 不能为空")
    old = get_api_key(key) or {
        "api_key": key, "name": "", "strategy": 1,
        "rpm_limit": 0, "concurrency_limit": 0, "enabled": 1,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    def _int_field(field: str) -> int:
        v = rec.get(field)
        if v is None or v == "":
            v = old.get(field, 0)
        return int(v or 0)

    name = str(rec.get("name") if rec.get("name") is not None else old.get("name") or "").strip()
    strategy = _int_field("strategy") or 1
    if strategy not in (1, 2):
        raise ValueError("strategy 只能是 1（填充/固定）或 2（轮询）")
    rpm_limit = max(0, _int_field("rpm_limit"))
    concurrency_limit = max(0, _int_field("concurrency_limit"))
    # enabled 未显式传入时保留旧值（避免「只改限额」把停用的 key 静默启用）
    if rec.get("enabled") is None:
        enabled = int(old.get("enabled", 1))
    else:
        enabled = 1 if rec.get("enabled") else 0

    with get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO allowed_keys "
            "(api_key, name, strategy, rpm_limit, concurrency_limit, enabled, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (key, name, strategy, rpm_limit, concurrency_limit, enabled, old["created_at"]),
        )
    _invalidate_cache()
    return {
        "api_key": key, "name": name, "strategy": strategy,
        "rpm_limit": rpm_limit, "concurrency_limit": concurrency_limit,
        "enabled": enabled, "created_at": old["created_at"],
    }


def delete_api_key(api_key: str) -> bool:
    with get_db() as conn:
        res = conn.execute("DELETE FROM allowed_keys WHERE api_key = ?", (api_key,))
    _invalidate_cache()
    return bool(res.rowcount)


def _invalidate_cache() -> None:
    global _CFG_CACHE, _CFG_TS
    _CFG_CACHE = None
    _CFG_TS = 0.0


def load_config() -> dict[str, Any]:
    """读网关配置。5s 内复用缓存，避免 UI 轮询每次开库抢锁。"""
    global _CFG_CACHE, _CFG_TS
    now = time.time()
    if _CFG_CACHE is not None and (now - _CFG_TS) < _CFG_TTL:
        return _CFG_CACHE
    with get_db() as conn:
        res = conn.execute("SELECT value FROM settings WHERE key = 'auth_required'").fetchone()
        auth_required = (res[0] == "1") if res else False

        rows = conn.execute(
            "SELECT api_key, name, strategy, rpm_limit, concurrency_limit, enabled, created_at "
            "FROM allowed_keys ORDER BY created_at, api_key").fetchall()
        api_keys = [_row_to_key(r) for r in rows]
        # 兼容旧调用方：allowed_keys = 已启用的 key 列表
        allowed_keys = [k["api_key"] for k in api_keys if k["enabled"]]

        res_tok = conn.execute("SELECT value FROM settings WHERE key = 'gateway_token'").fetchone()
        gateway_token = admin_password() or (res_tok[0] if res_tok else "admin")

    _CFG_CACHE = {
        "auth_required": auth_required,
        "allowed_keys": allowed_keys,
        "api_keys": api_keys,
        "gateway_token": gateway_token,
    }
    _CFG_TS = now
    return _CFG_CACHE


def save_config(config: dict[str, Any]) -> None:
    with get_db() as conn:
        auth_required_str = "1" if config.get("auth_required", False) else "0"
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('auth_required', ?)",
            (auth_required_str,)
        )

        if "gateway_token" in config:
            conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES ('gateway_token', ?)",
                (str(config["gateway_token"]),)
            )

        # 兼容旧前端的 string[] 写法：只增删 key，**不清空**已配置的名称/策略/限额
        # （原实现是全删全插，会把新字段一起抹掉）
        if "allowed_keys" in config:
            incoming = [str(k).strip() for k in (config["allowed_keys"] or []) if str(k).strip()]
            stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
            for key in incoming:
                conn.execute(
                    "INSERT OR IGNORE INTO allowed_keys "
                    "(api_key, name, strategy, rpm_limit, concurrency_limit, enabled, created_at) "
                    "VALUES (?, '', 1, 0, 0, 1, ?)", (key, stamp),
                )
            if incoming:
                holders = ",".join("?" * len(incoming))
                conn.execute(f"DELETE FROM allowed_keys WHERE api_key NOT IN ({holders})",
                             tuple(incoming))
            else:
                conn.execute("DELETE FROM allowed_keys")
    _invalidate_cache()
