# content-curator/app/config.py
"""Configuration management — reads from SQLite settings table."""
import json
import os
import sqlite3
from pathlib import Path
from .database import get_db

# Static env-based config (not user-editable at runtime)
SF_API_KEY = os.environ.get("SF_API_KEY", "")
COOKIES_FILE = os.environ.get("COOKIES_FILE", "/app/cookies.txt")
CACHE_DIR = Path(os.environ.get("CACHE_DIR", "/app/cache"))
HELPER_SERVER = os.environ.get("HELPER_SERVER", "http://127.0.0.1:9101")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}


def get_setting(key: str, default: str = "") -> str:
    conn = get_db()
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


def get_setting_json(key: str, default=None):
    val = get_setting(key, "")
    if not val:
        return default or {}
    try:
        return json.loads(val)
    except json.JSONDecodeError:
        return default or {}


def set_setting(key: str, value: str):
    conn = get_db()
    conn.execute(
        "INSERT INTO settings(key, value, updated_at) VALUES(?, ?, datetime('now')) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (key, value)
    )
    conn.commit()
    conn.close()


def set_setting_json(key: str, value):
    set_setting(key, json.dumps(value, ensure_ascii=False))


def get_vault_path() -> Path:
    return Path(get_setting("vault_path", "/app/vault"))


def get_ai_config() -> dict:
    return get_setting_json("ai_config", {
        "api_base": "https://api.siliconflow.cn/v1",
        "text_model": "deepseek-ai/DeepSeek-V3",
        "vision_model": "Qwen/Qwen3-VL-8B-Instruct",
        "temperature": 0.3,
        "max_tokens": 2500
    })


def get_whisper_config() -> dict:
    return get_setting_json("whisper_config", {
        "mode": "cloud", "model_size": "base", "language": "zh"
    })


def get_domain_taxonomy() -> dict:
    return get_setting_json("domain_taxonomy", {})


def get_sessdata() -> str:
    """Read SESSDATA from DB first, fallback to cookies file."""
    val = get_setting("sessdata", "")
    if val:
        return val
    try:
        for line in Path(COOKIES_FILE).read_text().splitlines():
            if line.strip().startswith("#") or not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) >= 7 and parts[5].strip() == "SESSDATA":
                return parts[6]
    except Exception:
        pass
    return ""
