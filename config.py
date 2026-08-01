"""Bot configuration — loaded from environment / .env file."""

import os
import sys
from dotenv import load_dotenv

load_dotenv()

# ─── Required credentials ─────────────────────────────────────────────────────
API_ID = os.environ.get("API_ID")
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
OWNER_ID = os.environ.get("OWNER_ID")

_missing: list[str] = []
if not API_ID:
    _missing.append("API_ID")
if not API_HASH:
    _missing.append("API_HASH")
if not BOT_TOKEN:
    _missing.append("BOT_TOKEN")
if not OWNER_ID:
    _missing.append("OWNER_ID")

if _missing:
    print(f"[FATAL] Missing required env vars: {', '.join(_missing)}")
    print("Set them in a .env file or export them before running.")
    sys.exit(1)

API_ID = int(API_ID)
OWNER_ID = int(OWNER_ID)

# ─── Optional settings ────────────────────────────────────────────────────────
_log_channel = os.environ.get("LOG_CHANNEL")
LOG_CHANNEL = int(_log_channel) if _log_channel else None

MAX_FILE_SIZE = int(
    os.environ.get("MAX_FILE_SIZE", str(4 * 1024 * 1024 * 1024))
)  # 4 GB default

PREMIUM_LIMIT = int(os.environ.get("PREMIUM_LIMIT", "5"))
