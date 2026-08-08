"""Environment and app-wide constants."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

APP_NAME = "shopper"

# LiteLLM reads ANTHROPIC_API_KEY straight from the environment, so loading
# .env above is what authenticates the model.
MODEL_ID = "anthropic/claude-opus-5"

# Local SQLite, as intended — but ADK 2.6.1 builds an async engine, so the
# sync pysqlite driver is rejected. Same demo.db file, async driver.
DB_URL = "sqlite+aiosqlite:///./demo.db"

# Durable preferences. The "user:" prefix is what makes ADK persist this
# across sessions rather than scoping it to one conversation.
PROFILE_STATE_KEY = "user:profile"

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")


def require_telegram_token() -> str:
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN missing from .env")
    return TELEGRAM_BOT_TOKEN


def session_id_for(telegram_user_id: int | str) -> str:
    """One long-lived session per Telegram user."""
    return f"tg-{telegram_user_id}"
