from typing import Any
import time

from .database import get_db
from .env import admin_password

_CFG_CACHE: dict[str, Any] | None = None
_CFG_TS = 0.0
_CFG_TTL = 5.0


def load_config() -> dict[str, Any]:
    """读网关配置。5s 内复用缓存，避免 UI 轮询每次开库抢锁。"""
    global _CFG_CACHE, _CFG_TS
    now = time.time()
    if _CFG_CACHE is not None and (now - _CFG_TS) < _CFG_TTL:
        return _CFG_CACHE
    with get_db() as conn:
        res = conn.execute("SELECT value FROM settings WHERE key = 'auth_required'").fetchone()
        auth_required = (res[0] == "1") if res else False

        rows = conn.execute("SELECT api_key FROM allowed_keys").fetchall()
        allowed_keys = [r[0] for r in rows]

        res_tok = conn.execute("SELECT value FROM settings WHERE key = 'gateway_token'").fetchone()
        gateway_token = admin_password() or (res_tok[0] if res_tok else "admin")

    _CFG_CACHE = {
        "auth_required": auth_required,
        "allowed_keys": allowed_keys,
        "gateway_token": gateway_token
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
            
        if "allowed_keys" in config:
            conn.execute("DELETE FROM allowed_keys")
            for key in config["allowed_keys"]:
                conn.execute("INSERT OR REPLACE INTO allowed_keys (api_key) VALUES (?)", (key,))
    global _CFG_CACHE, _CFG_TS
    _CFG_CACHE = None
    _CFG_TS = 0.0
