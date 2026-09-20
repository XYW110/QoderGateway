import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from .env import load_dotenv

load_dotenv()

DB_PATH = Path.home() / ".qoder" / "qoder2api.db"


def get_db():
    # timeout + WAL + busy_timeout：多线程注册入库时避免 database is locked
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_db() as conn:
        # Accounts Table
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS accounts (
                uid TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                user_type TEXT,
                security_oauth_token TEXT NOT NULL,
                refresh_token TEXT NOT NULL,
                machine_id TEXT NOT NULL,
                enabled INTEGER DEFAULT 1,
                last_status TEXT DEFAULT 'ok',
                last_error TEXT,
                quota INTEGER DEFAULT 0,
                is_quota_exceeded INTEGER DEFAULT 0,
                plan TEXT,
                user_tag TEXT,
                next_reset_at INTEGER
            )
            """
        )
        
        # Allowed API Keys Table (for proxy routing auth)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS allowed_keys (
                api_key TEXT PRIMARY KEY,
                name TEXT,
                strategy INTEGER DEFAULT 1,
                rpm_limit INTEGER DEFAULT 0,
                concurrency_limit INTEGER DEFAULT 0,
                enabled INTEGER DEFAULT 1,
                created_at TEXT
            )
            """
        )
        
        # Global Settings Table
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )
        
        # Set default gateway token if not present
        res = conn.execute("SELECT value FROM settings WHERE key = 'gateway_token'").fetchone()
        if not res:
            default_token = os.getenv("QODER_ADMIN_PASSWORD", "admin").strip() or "admin"
            conn.execute("INSERT INTO settings (key, value) VALUES ('gateway_token', ?)", (default_token,))
            
        res_auth = conn.execute("SELECT value FROM settings WHERE key = 'auth_required'").fetchone()
        if not res_auth:
            conn.execute("INSERT INTO settings (key, value) VALUES ('auth_required', '0')")

        # token_expires_at 列（幂等：已存在则忽略）
        try:
            conn.execute("ALTER TABLE accounts ADD COLUMN token_expires_at TEXT")
        except Exception:
            pass

        # email / password 列（幂等：已存在则忽略）
        # password 为注册时随机生成，落库仅用于本地管理，切勿外泄
        for _ddl in (
            "ALTER TABLE accounts ADD COLUMN email TEXT",
            "ALTER TABLE accounts ADD COLUMN password TEXT",
        ):
            try:
                conn.execute(_ddl)
            except Exception:
                pass

        # allowed_keys 扩展列：名称 / 路由策略 / RPM / 并发 / 启用（幂等，老库自动补齐）
        # strategy: 1=填充(同 key+模型固定账号) 2=轮询(每次请求依次下一个)；limit 0=不限
        for _ddl in (
            "ALTER TABLE allowed_keys ADD COLUMN name TEXT",
            "ALTER TABLE allowed_keys ADD COLUMN strategy INTEGER DEFAULT 1",
            "ALTER TABLE allowed_keys ADD COLUMN rpm_limit INTEGER DEFAULT 0",
            "ALTER TABLE allowed_keys ADD COLUMN concurrency_limit INTEGER DEFAULT 0",
            "ALTER TABLE allowed_keys ADD COLUMN enabled INTEGER DEFAULT 1",
            "ALTER TABLE allowed_keys ADD COLUMN created_at TEXT",
        ):
            try:
                conn.execute(_ddl)
            except Exception:
                pass


init_db()
