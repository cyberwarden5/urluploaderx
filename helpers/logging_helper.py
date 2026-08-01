import logging
import sys
import asyncio
from datetime import datetime
from typing import Optional

from pyrogram import Client, enums

from config import LOG_CHANNEL

_handler = logging.StreamHandler(sys.stdout)
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

_file_handler = logging.FileHandler("bot.log", encoding="utf-8")

_formatter = logging.Formatter(
    fmt="[%(asctime)s] [%(levelname)s] %(name)s │ %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
_handler.setFormatter(_formatter)
_file_handler.setFormatter(_formatter)

logging.basicConfig(
    level=logging.INFO,
    handlers=[_handler, _file_handler],
)

logger = logging.getLogger("URLUploaderBot")

_log_tasks: set[asyncio.Task] = set()


def _track_task(task: asyncio.Task) -> None:
    _log_tasks.add(task)
    task.add_done_callback(_log_tasks.discard)


async def log_to_channel(client: Optional[Client], message: str) -> None:
    if not LOG_CHANNEL or not client:
        return
    try:
        await client.send_message(
            LOG_CHANNEL, message, parse_mode=enums.ParseMode.HTML
        )
    except Exception as e:
        logger.warning("Failed to send log to channel %s: %s", LOG_CHANNEL, e)


async def send_event_log(
    client: Optional[Client],
    event_type: str,
    user_id: int,
    user_name: str = "",
    details: str = "",
) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.info("EVENT │ [%s] │ User %s │ %s", event_type, user_id, details)

    if LOG_CHANNEL and client:
        bot_name = client.me.first_name if (hasattr(client, "me") and client.me) else "Bot"
        html_msg = (
            f"⚙️ <b>[{bot_name}] System Event: {event_type}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 <b>User:</b> <a href='tg://user?id={user_id}'>{user_name or 'User'}</a>\n"
            f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
            f"📝 <b>Details:</b> {details}\n"
            f"🕒 <b>Time:</b> <code>{timestamp}</code>"
        )
        task = asyncio.create_task(log_to_channel(client, html_msg))
        _track_task(task)
