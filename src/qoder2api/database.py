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
                api_key TEXT PRIMARY KEY
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


init_db()
