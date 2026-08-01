import os
import sys
import time
import asyncio
import logging
import shutil
import platform
import unicodedata
import signal
from datetime import datetime, timezone

def force_exit(sig, frame):
    print("\n[!] Force exiting immediately...")
    os._exit(0)

signal.signal(signal.SIGINT, force_exit)
signal.signal(signal.SIGTERM, force_exit)

# Initialize asyncio event loop prior to any Pyrogram/Submodule imports
try:
    loop = asyncio.get_running_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

# ─── Time-sync ───────────────────────────────────────────────────────────────
_DRIFT = 0.0

# ─── High-Speed Cryptography AES Monkeypatch ─────────────────────────────────
try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.backends import default_backend
    import pyrogram.crypto.aes

    def ige_cryptography(data: bytes, key: bytes, iv: bytes, encrypt: bool) -> bytes:
        backend = default_backend()
        cipher = Cipher(algorithms.AES(key), modes.ECB(), backend=backend)
        encryptor = cipher.encryptor() if encrypt else cipher.decryptor()
        
        iv_1 = iv[:16]
        iv_2 = iv[16:]
        
        chunks = [data[i: i + 16] for i in range(0, len(data), 16)]
        out_chunks = []
        
        for chunk in chunks:
            if encrypt:
                x1 = bytes(a ^ b for a, b in zip(chunk, iv_1))
                enc = encryptor.update(x1)
                c = bytes(a ^ b for a, b in zip(enc, iv_2))
                out_chunks.append(c)
                iv_1 = c
                iv_2 = chunk
            else:
                x2 = bytes(a ^ b for a, b in zip(chunk, iv_2))
                dec = encryptor.update(x2)
                p = bytes(a ^ b for a, b in zip(dec, iv_1))
                out_chunks.append(p)
                iv_1 = chunk
                iv_2 = p
                
        return b"".join(out_chunks)

    def ige256_encrypt_patched(data: bytes, key: bytes, iv: bytes) -> bytes:
        return ige_cryptography(data, key, iv, True)

    def ige256_decrypt_patched(data: bytes, key: bytes, iv: bytes) -> bytes:
        return ige_cryptography(data, key, iv, False)

    def ctr256_encrypt_cryptography(data: bytes, key: bytes, iv: bytearray, state: bytearray = None) -> bytes:
        backend = default_backend()
        cipher = Cipher(algorithms.AES(key), modes.CTR(bytes(iv)), backend=backend)
        encryptor = cipher.encryptor()
        
        out = encryptor.update(data) + encryptor.finalize()
        
        num_blocks = (len(data) + (state[0] if state else 0)) // 16
        rem_bytes = (len(data) + (state[0] if state else 0)) % 16
        
        val = int.from_bytes(iv, "big") + num_blocks
        iv[:] = val.to_bytes(16, "big")
        
        if state is not None:
            state[0] = rem_bytes
            
        return out

    pyrogram.crypto.aes.ige256_encrypt = ige256_encrypt_patched
    pyrogram.crypto.aes.ige256_decrypt = ige256_decrypt_patched
    pyrogram.crypto.aes.ctr256_encrypt = ctr256_encrypt_cryptography
    pyrogram.crypto.aes.ctr256_decrypt = ctr256_encrypt_cryptography
    print("[TimeSync] High-speed Cryptography monkeypatch applied to Pyrogram (C-level speeds).")
except Exception as e:
    print(f"[WARNING] Cryptography monkeypatch failed: {e}")

# ─── Pyrogram imports ─────────────────────────────────────────────────────────

from pyrogram import Client, filters, enums
from pyrogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InputMediaPhoto,
)

import config
from helpers.db import (
    is_user_registered,
    register_user,
    get_total_users_count,
    get_all_user_ids,
    get_user_role,
    is_user_banned,
    ban_user,
    unban_user,
    set_user_role,
    get_user_by_id_or_username,
    load_users,
    register_download,
    get_download_info,
)
from helpers.logging_helper import logger, send_event_log
from helpers.utils import (
    async_download_file,
    get_file_size,
    get_filename,
    file_size_format,
    delete_file,
    progress,
    progressArgs,
    get_system_status,
    cleanup_old_downloads,
    run_speedtest,
)
from helpers.ss_generator import extract_video_screenshots

# ─── Constants ────────────────────────────────────────────────────────────────
BOT_START_TIME = time.time()
VIDEO_EXTENSIONS = (
    ".mp4", ".mkv", ".avi", ".mov", ".webm",
    ".flv", ".wmv", ".m4v", ".3gp", ".ts",
)
BOT_VERSION = "2.1.0"

# Mutable state
user_states: dict[int, dict] = {}
active_tasks: dict[int, list] = {}

# ─── Bot client ───────────────────────────────────────────────────────────────
bot = Client(
    name="URLUploaderBot",
    api_id=config.API_ID,
    api_hash=config.API_HASH,
    bot_token=config.BOT_TOKEN,
    workdir="data",
    workers=8,
    max_concurrent_transmissions=1,
)


# ─── Box UI helper ────────────────────────────────────────────────────────────
def _box(title: str) -> str:
    """Build a monospace-aligned box header wrapped in <pre>."""
    import unicodedata
    def _vis_width(s: str) -> int:
        return sum(
            2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
            for ch in s
        )
    width = 29
    tw = _vis_width(title)
    pad = max(0, width - tw)
    left_pad = pad // 2
    right_pad = pad - left_pad
    return (
        f"<pre>"
        f"╔{'═' * width}╗\n"
        f"║{' ' * left_pad}{title}{' ' * right_pad}║\n"
        f"╚{'═' * width}╝"
        f"</pre>"
    )


# ─── Decorator: registration_required ─────────────────────────────────────────
def registration_required(func):
    """Ensure the user is registered before processing."""

    async def wrapper(client: Client, message: Message, *args, **kwargs):
        user = message.from_user
        if not user:
            return

        # Skip stale messages
        if message.date:
            msg_ts = (
                message.date.timestamp()
                if message.date.tzinfo
                else message.date.replace(tzinfo=timezone.utc).timestamp()
            )
            logger.info(f"INCOMING MESSAGE │ user={user.id} ({user.first_name}) │ text={message.text or '[Media/Command]'} │ msg_ts={msg_ts:.1f} vs start_time={BOT_START_TIME:.1f} │ diff={msg_ts - BOT_START_TIME:.1f}s")
            if msg_ts < BOT_START_TIME - 30.0:
                logger.info(f"Stale message ignored (sent {msg_ts - BOT_START_TIME:.1f}s before bot startup)")
                return

        # Check if banned
        if await is_user_banned(user.id):
            await message.reply_text("⛔ <b>You are banned from using this bot.</b>")
            return

        is_new = await register_user(user.id, user.first_name, user.username or "")
        if is_new:
            await send_event_log(
                client,
                "USER_REGISTRATION",
                user.id,
                f"{user.first_name} (@{user.username or 'N/A'})",
                "New user auto-registered.",
            )
        return await func(client, message, *args, **kwargs)

    return wrapper


# ─── /start ───────────────────────────────────────────────────────────────────
@bot.on_message(filters.command("start") & filters.private)
@registration_required
async def start_command(client: Client, message: Message):
    user = message.from_user
    logger.info("/start from %s (%s)", user.id, user.first_name)
    await send_event_log(client, "CMD_START", user.id, user.first_name)

    text = (
        f"{_box('⚡  URL UPLOADER PRO  ⚡')}\n\n"
        f"Hello {user.mention}!\n"
        f"I am your high-speed cloud file transporter.\n\n"
        f"▸ <b>Direct Links</b> — Download &amp; re-upload (up to 4 GB)\n"
        f"▸ <b>Rename</b> — Custom file names on-the-fly\n"
        f"▸ <b>Screenshots</b> — Frame captures &amp; grid collage\n"
        f"▸ <b>Live Tracking</b> — Speed, ETA, progress bar\n\n"
        f"<i>Send a direct download URL to begin.</i>"
    )
    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("📖 Help", callback_data="cb_help"),
                InlineKeyboardButton("📊 Status", callback_data="cb_status"),
            ],
            [
                InlineKeyboardButton(
                    "👨‍💻 Developer", url="https://t.me/AftabKabir"
                ),
            ],
        ]
    )
    await message.reply_text(
        text, reply_markup=kb, disable_web_page_preview=True
    )


# ─── /help ────────────────────────────────────────────────────────────────────
@bot.on_message(filters.command("help") & filters.private)
@registration_required
async def help_command(client: Client, message: Message):
    user = message.from_user
    await send_event_log(client, "CMD_HELP", user.id, user.first_name)

    text = (
        f"{_box('📖  URL UPLOADER GUIDE')}\n\n"
        "💎 <b>Upload a file:</b>\n"
        "  1. Send any direct HTTP/HTTPS link.\n"
        "  2. Tap <b>Default Upload</b> or <b>Rename File</b>.\n\n"
        "🎬 <b>Screenshots (<code>/ss</code>):</b>\n"
        "  • Reply to a video or video link with <code>/ss</code>\n"
        "  • Optional: <code>/ss 15</code> (1–30 frames)\n\n"
        "🛠 <b>General Commands:</b>\n"
        "  ├ <code>/start</code> — Welcome menu\n"
        "  ├ <code>/help</code> — This guide\n"
        "  ├ <code>/status</code> — Server metrics\n"
        "  └ <code>/ss</code> — Screenshot generator\n\n"
        "👑 <b>Owner-Only Commands:</b>\n"
        "  ├ <code>/ping</code> — Bot ping latency\n"
        "  ├ <code>/speedtest</code> — Server speed test\n"
        "  ├ <code>/ban</code> &lt;user_id/username&gt; — Ban a user\n"
        "  ├ <code>/unban</code> &lt;user_id/username&gt; — Unban a user\n"
        "  ├ <code>/promote</code> &lt;user_id/username&gt; — Promote to Premium\n"
        "  ├ <code>/demote</code> &lt;user_id/username&gt; — Demote to Free\n"
        "  ├ <code>/files</code> — Paginated local files manager\n"
        "  ├ <code>/logs</code> — Send bot log.txt file\n"
        "  ├ <code>/restart</code> — Restart bot process\n"
        "  └ <code>/shell</code> &lt;cmd&gt; — Execute shell command"
    )
    await message.reply_text(text, reply_to_message_id=message.id)


# ─── /status ──────────────────────────────────────────────────────────────────
@bot.on_message(filters.command("status") & filters.private)
@registration_required
async def status_command(client: Client, message: Message):
    user = message.from_user

    ping_msg = await message.reply_text("⚡ Measuring server metrics…")

    # Measure actual API ping
    t0 = time.time()
    await ping_msg.edit_text("⚡")
    ping_ms = round((time.time() - t0) * 1000, 2)

    stats = await get_system_status()
    uptime_s = int(time.time() - BOT_START_TIME)
    days = uptime_s // 86400
    hours = (uptime_s % 86400) // 3600
    mins = (uptime_s % 3600) // 60
    secs = uptime_s % 60
    uptime_str = f"{days}d {hours}h {mins}m {secs}s" if days else f"{hours}h {mins}m {secs}s"

    total_users = await get_total_users_count()
    active_downloads = len(active_tasks)
    pending_states = len(user_states)
    is_owner = user.id == config.OWNER_ID
    badge = "👑 Owner" if is_owner else "👤 User"

    await send_event_log(
        client, "CMD_STATUS", user.id, user.first_name, f"ping={ping_ms}ms"
    )

    text = (
        f"{_box('📊  SERVER STATUS')}\n\n"
        f"<b>Access Level:</b> {badge}\n\n"
        f"┌────────────── <b>NETWORK</b> ──────────────┐\n"
        f"│  🔹 <b>Ping:</b>       <code>{ping_ms} ms</code>\n"
        f"│  🔹 <b>Bot Version:</b> <code>v{BOT_VERSION}</code>\n"
        f"│  🔹 <b>Uptime:</b>     <code>{uptime_str}</code>\n"
        f"└────────────────────────────────────┘\n\n"
        f"┌────────────── <b>SYSTEM</b> ──────────────┐\n"
        f"│  💻 <b>OS:</b>         <code>{stats.get('platform', 'N/A')}</code>\n"
        f"│  ⚙️ <b>Python:</b>     <code>{stats.get('python', 'N/A')}</code>\n"
        f"│  🔌 <b>CPU Cores:</b>  <code>{stats.get('cpu_count', 'N/A')}</code>\n"
        f"│  💻 <b>CPU Usage:</b>  <code>{stats['cpu']}%</code>\n"
        f"└────────────────────────────────────┘\n\n"
        f"┌────────────── <b>MEMORY</b> ─────────────┐\n"
        f"│  🧠 <b>RAM Usage:</b>  <code>{stats['ram_usage']}%</code>\n"
        f"│  📊 <b>RAM Used:</b>   <code>{stats['ram_used']}</code> / <code>{stats['ram_total']}</code>\n"
        f"│  📊 <b>Swap:</b>       <code>{stats.get('swap_usage', 'N/A')}</code>\n"
        f"└────────────────────────────────────┘\n\n"
        f"┌────────────── <b>STORAGE</b> ────────────┐\n"
        f"│  💾 <b>Disk Usage:</b> <code>{stats['disk_usage']}%</code>\n"
        f"│  📊 <b>Disk Used:</b>  <code>{stats['disk_used']}</code> / <code>{stats['disk_total']}</code>\n"
        f"│  📂 <b>Downloads:</b>  <code>{stats.get('download_count', 0)}</code> files cached\n"
        f"└────────────────────────────────────┘\n\n"
        f"┌────────────── <b>ACTIVITY</b> ───────────┐\n"
        f"│  👥 <b>Users:</b>       <code>{total_users}</code>\n"
        f"│  ⬇️ <b>Active DLs:</b>  <code>{active_downloads}</code>\n"
        f"│  ⏳ <b>Pending:</b>     <code>{pending_states}</code>\n"
        f"└────────────────────────────────────┘"
    )
    await ping_msg.edit_text(text)


# ─── /users (owner) ──────────────────────────────────────────────────────────
@bot.on_message(filters.command("users") & filters.private)
@registration_required
async def users_command(client: Client, message: Message):
    user = message.from_user
    if user.id != config.OWNER_ID:
        return await message.reply_text("⛔ <b>Owner-only command.</b>")

    total = await get_total_users_count()
    await send_event_log(client, "CMD_USERS", user.id, user.first_name)
    await message.reply_text(
        f"{_box('👥  REGISTERED USERS')}\n\n"
        f"Total users in database: <code>{total}</code>"
    )


# ─── /broadcast (owner) ─────────────────────────────────────────────────────
@bot.on_message(filters.command("broadcast") & filters.private)
@registration_required
async def broadcast_command(client: Client, message: Message):
    user = message.from_user
    if user.id != config.OWNER_ID:
        return await message.reply_text("⛔ <b>Owner-only command.</b>")

    if not message.reply_to_message:
        return await message.reply_text(
            "⚠️ <b>Reply to a message to broadcast it.</b>"
        )

    users = await get_all_user_ids()
    status_msg = await message.reply_text(
        f"{_box('📢  BROADCAST')}\n\n"
        f"Sending to <code>{len(users)}</code> users…"
    )

    ok = fail = 0
    for uid in users:
        try:
            await message.reply_to_message.copy(chat_id=uid)
            ok += 1
            await asyncio.sleep(0.05)
        except Exception:
            fail += 1

    await status_msg.edit_text(
        f"{_box('📢  BROADCAST COMPLETE')}\n\n"
        f"🎯 <b>Sent:</b>     <code>{ok}</code>\n"
        f"❌ <b>Failed:</b>   <code>{fail}</code>\n"
        f"📊 <b>Total:</b>    <code>{ok + fail}</code>"
    )
    await send_event_log(
        client, "CMD_BROADCAST", user.id, user.first_name, f"ok={ok} fail={fail}"
    )


async def check_task_limit(user_id: int) -> tuple[bool, str]:
    """Returns (is_allowed, error_msg)"""
    role = await get_user_role(user_id)
    active_list = [t for t in active_tasks.get(user_id, []) if not t.done()]
    
    if role == "free":
        if len(active_list) >= 1:
            return False, "<b>⚠️ Concurrency Limit Reached!</b>\n\nFree users are only allowed to run 1 task at a time. Please wait for your current task to complete or cancel it."
    elif role == "premium":
        if len(active_list) >= config.PREMIUM_LIMIT:
            return False, f"<b>⚠️ Concurrency Limit Reached!</b>\n\nPremium users are allowed to run up to {config.PREMIUM_LIMIT} concurrent tasks. Please wait for some to finish."
    return True, ""


# ─── /ss ──────────────────────────────────────────────────────────────────────
@bot.on_message(filters.command("ss") & filters.private)
@registration_required
async def ss_command(client: Client, message: Message):
    user = message.from_user
    
    allowed, limit_msg = await check_task_limit(user.id)
    if not allowed:
        return await message.reply_text(limit_msg, reply_to_message_id=message.id)
    
    args = message.text.split()
    count = 10
    if len(args) > 1 and args[1].isdigit():
        count = max(1, min(30, int(args[1])))

    replied = message.reply_to_message
    temp_dir = os.path.join("temp", f"ss_{user.id}_{int(time.time())}")
    video_source: str | None = None

    try:
        if replied and (replied.video or replied.document):
            file_obj = replied.video or replied.document
            fname = getattr(file_obj, "file_name", "video.mp4") or "video.mp4"
            if not fname.lower().endswith(VIDEO_EXTENSIONS) and not replied.video:
                return await message.reply_text(
                    "⚠️ <b>Unsupported video format!</b>",
                    reply_to_message_id=message.id
                )

            status_msg = await message.reply_text("📥 <b>Downloading video…</b>", reply_to_message_id=message.id)
            os.makedirs(temp_dir, exist_ok=True)
            video_source = await client.download_media(
                replied,
                file_name=os.path.join(temp_dir, "input_video.mp4"),
                progress=progress,
                progress_args=progressArgs("Video Download", status_msg, time.time()),
            )

        elif (
            replied
            and replied.text
            and replied.text.startswith(("http://", "https://"))
        ):
            url = replied.text.strip()
            status_msg = await message.reply_text(
                "🌐 <b>Downloading File from URL…</b>",
                reply_to_message_id=message.id
            )
            os.makedirs(temp_dir, exist_ok=True)
            video_source = await async_download_file(
                url,
                "input_video.mp4",
                progress=progress,
                progress_args=progressArgs("URL Download", status_msg, time.time()),
                temp_dir=temp_dir,
            )
        else:
            return await message.reply_text(
                "⚠️ <b>Reply to a video or video link with <code>/ss [count]</code></b>",
                reply_to_message_id=message.id
            )

        await status_msg.edit_text(
            f"{_box('🎬  SCREENSHOTS')}\n\n"
            f"🎬 <b>Extracting:</b> <code>0</code> / <code>{count}</code> frames\n"
            f"<code>[▱▱▱▱▱▱▱▱▱▱▱▱▱]</code>"
        )

        loop = asyncio.get_running_loop()
        last_edit_time = 0.0

        def ss_progress(current, total):
            nonlocal last_edit_time
            now = time.time()
            if now - last_edit_time < 1.5 and current < total:
                return
            last_edit_time = now
            pct = (current / total) * 100
            filled = int((pct * 13) / 100)
            bar = "▰" * filled + "▱" * (13 - filled)
            text = (
                f"{_box('🎬  SCREENSHOTS')}\n\n"
                f"🎬 <b>Extracting:</b> <code>{current}</code> / <code>{total}</code> frames\n"
                f"<code>[{bar}]</code>"
            )
            asyncio.run_coroutine_threadsafe(
                status_msg.edit_text(text),
                loop
            )

        extracted, collage_path = await extract_video_screenshots(
            video_source, temp_dir, count=count, progress_cb=ss_progress
        )

        await status_msg.edit_text(
            f"{_box('📤  UPLOADING')}\n\n"
            f"📤 <b>Uploading screenshots to Telegram…</b>\n"
            f"<code>[▱▱▱▱▱▱▱▱▱▱▱▱▱]</code>"
        )

        media = [
            InputMediaPhoto(
                media=item["path"],
                caption=f"🕒 Timestamp: {item['timestamp']}"
            )
            for item in extracted
        ]

        for i in range(0, len(media), 10):
            await client.send_media_group(
                chat_id=message.chat.id,
                media=media[i : i + 10],
                reply_to_message_id=message.id,
            )

        await status_msg.delete()
        await send_event_log(
            client, "SS_GENERATE", user.id, user.first_name, f"{count} screenshots"
        )

    except Exception as e:
        logger.error("/ss error: %s", e, exc_info=True)
        await message.reply_text(f"❌ <b>Screenshot failed:</b> <code>{e}</code>")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


# ─── URL handler ──────────────────────────────────────────────────────────────
@bot.on_message(
    filters.private
    & filters.text
    & ~filters.regex(r"^/")
)
@registration_required
async def url_handler(client: Client, message: Message):
    user_id = message.from_user.id
    text = message.text.strip()
    if text.startswith("/"):
        return

    allowed, limit_msg = await check_task_limit(user_id)
    if not allowed:
        return await message.reply_text(limit_msg, reply_to_message_id=message.id)

    # Handle rename state
    state = user_states.pop(user_id, None)
    if state and state.get("action") == "awaiting_rename":
        await _process_download(
            client,
            message,
            state["url"],
            custom_filename=text,
            original_message_id=state.get("original_message_id"),
            user=message.from_user,
        )
        return

    if not text.startswith(("http://", "https://")):
        return

    msg = await message.reply_text("🔍 <b>Fetching URL info…</b>")
    try:
        file_size = await get_file_size(text)
        filename = await get_filename(text)

        if file_size > config.MAX_FILE_SIZE:
            return await msg.edit_text(
                f"{_box('❌  FILE TOO LARGE')}\n\n"
                f"📁 <b>Name:</b> <code>{filename}</code>\n"
                f"📦 <b>Size:</b> <code>{file_size_format(file_size)}</code>\n"
                f"⚠️ <b>Limit:</b> <code>{file_size_format(config.MAX_FILE_SIZE)}</code>"
            )

        size_str = file_size_format(file_size) if file_size > 0 else "Unknown"
        info = (
            f"{_box('📥  URL DETECTED')}\n\n"
            f"📁 <b>Name:</b> <code>{filename}</code>\n"
            f"📦 <b>Size:</b> <code>{size_str}</code>\n\n"
            f"<i>Choose an option:</i>"
        )
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("🚀 Default Upload", callback_data="up_def"),
                    InlineKeyboardButton("✏️ Rename File", callback_data="up_ren"),
                ],
                [
                    InlineKeyboardButton("❌ Cancel", callback_data="up_cancel"),
                ],
            ]
        )

        user_states[user_id] = {
            "url": text,
            "filename": filename,
            "file_size": file_size,
            "message_id": msg.id,
            "original_message_id": message.id,
        }

        await msg.edit_text(info, reply_markup=kb)
        await send_event_log(
            client,
            "URL_DETECT",
            user_id,
            message.from_user.first_name,
            f"{filename} ({size_str})",
        )

    except Exception as e:
        logger.error("URL inspect error: %s", e)
        await msg.edit_text(f"❌ <b>Failed:</b> <code>{e}</code>")


# ─── Callback query handler ───────────────────────────────────────────────────
@bot.on_callback_query()
async def callback_handler(client: Client, cb: CallbackQuery):
    user_id = cb.from_user.id
    data = cb.data
    logger.info("CALLBACK QUERY │ user=%s (%s) │ data=%s", user_id, cb.from_user.first_name, data)

    if data.startswith("fpage:"):
        page = int(data.split(":")[1])
        await show_files_page(cb.message, page)
        return
    elif data.startswith("fsel:"):
        _, idx_str, page_str = data.split(":")
        await show_file_details(cb, int(idx_str), int(page_str))
        return
    elif data.startswith("fsend:"):
        _, idx_str, page_str = data.split(":")
        idx = int(idx_str)
        import os
        files = []
        if os.path.exists("downloads"):
            for f in os.listdir("downloads"):
                path = os.path.join("downloads", f)
                if os.path.isfile(path):
                    files.append(f)
            files.sort(key=lambda x: os.path.getmtime(os.path.join("downloads", x)), reverse=True)
        if idx < len(files):
            fname = files[idx]
            path = os.path.join("downloads", fname)
            logger.info("FILE MANAGER │ Sending file to owner: %s", fname)
            await cb.answer("📤 Uploading file with progress tracker...")
            ul_start = time.time()
            try:
                await cb.message.edit_text("📤 <b>Uploading file to owner…</b>")
                await client.send_document(
                    chat_id=cb.message.chat.id,
                    document=path,
                    caption=f"📄 <b>File:</b> <code>{fname}</code>",
                    progress=progress,
                    progress_args=progressArgs("Uploading", cb.message, ul_start),
                )
                logger.info("FILE MANAGER │ Successfully sent file: %s", fname)
            except Exception as e:
                logger.error("FILE MANAGER │ Failed to send file %s: %s", fname, e)
                try:
                    await cb.message.reply_text(f"❌ <b>Upload failed:</b> <code>{e}</code>")
                except Exception:
                    pass
        else:
            await cb.answer("❌ File no longer exists.", show_alert=True)
        return
    elif data.startswith("fdel:"):
        _, idx_str, page_str = data.split(":")
        idx = int(idx_str)
        page = int(page_str)
        import os
        files = []
        if os.path.exists("downloads"):
            for f in os.listdir("downloads"):
                path = os.path.join("downloads", f)
                if os.path.isfile(path):
                    files.append(f)
            files.sort(key=lambda x: os.path.getmtime(os.path.join("downloads", x)), reverse=True)
        if idx < len(files):
            fname = files[idx]
            path = os.path.join("downloads", fname)
            logger.info("FILE MANAGER │ Deleting file: %s", fname)
            if os.path.exists(path):
                os.remove(path)
            await cb.answer("🗑 File deleted.", show_alert=True)
        await show_files_page(cb.message, page)
        return
    elif data == "fdelall":
        logger.info("FILE MANAGER │ Owner requested to delete all downloaded files")
        keyboard = [
            [
                InlineKeyboardButton("✅ Yes, Delete All", callback_data="fdelall_confirm"),
                InlineKeyboardButton("❌ No, Go Back", callback_data="fpage:0")
            ]
        ]
        await cb.message.edit_text(
            "⚠️ <b>Are you sure you want to delete all downloaded files?</b>\n"
            "This action is irreversible.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    elif data == "fdelall_confirm":
        logger.info("FILE MANAGER │ Owner confirmed delete all files")
        import os
        count = 0
        if os.path.exists("downloads"):
            for f in os.listdir("downloads"):
                path = os.path.join("downloads", f)
                if os.path.isfile(path):
                    try:
                        os.remove(path)
                        count += 1
                    except Exception:
                        pass
        await cb.answer(f"🗑 Deleted {count} files.", show_alert=True)
        await show_files_page(cb.message, 0)
        return
    elif data == "fclose":
        await cb.message.delete()
        return
    elif data == "fnoop":
        await cb.answer()
        return

    # Navigation callbacks
    if data == "cb_help":
        text = (
            f"{_box('📖  HELP &amp; COMMANDS')}\n\n"
            "1️⃣ <b>Upload:</b> Send a direct link → choose upload/rename.\n"
            "2️⃣ <b>Screenshots:</b> Reply to video with <code>/ss [count]</code>.\n\n"
            "📋 <b>Commands:</b>\n"
            "  ├ <code>/start</code> — Welcome\n"
            "  ├ <code>/help</code> — Guide\n"
            "  ├ <code>/ss</code> — Screenshots\n"
            "  └ <code>/status</code> — Server stats"
        )
        await cb.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Back", callback_data="cb_start")]]
            ),
        )
        return

    if data == "cb_start":
        text = (
            f"{_box('⚡  URL UPLOADER PRO  ⚡')}\n\n"
            f"Hello {cb.from_user.mention}!\n"
            "Send a direct download URL to get started."
        )
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("📖 Help", callback_data="cb_help"),
                    InlineKeyboardButton("📊 Status", callback_data="cb_status"),
                ],
                [
                    InlineKeyboardButton(
                        "👨‍💻 Developer", url="https://t.me/itsSmartDev"
                    ),
                ],
            ]
        )
        await cb.message.edit_text(text, reply_markup=kb)
        return

    if data == "cb_status":
        stats = await get_system_status()
        text = (
            f"{_box('📊  QUICK STATUS')}\n\n"
            f"💻 <b>CPU:</b>  <code>{stats['cpu']}%</code>\n"
            f"🧠 <b>RAM:</b>  <code>{stats['ram_usage']}%</code>\n"
            f"💾 <b>Disk:</b> <code>{stats['disk_usage']}%</code>"
        )
        await cb.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Back", callback_data="cb_start")]]
            ),
        )
        return

    if data in ("up_cancel", "cancel_task"):
        user_states.pop(user_id, None)
        tasks = active_tasks.pop(user_id, [])
        for t in tasks:
            if t and not t.done():
                t.cancel()
        try:
            await cb.answer("❌ Cancelling task...", show_alert=True)
        except Exception:
            pass
        await cb.message.edit_text(f"{_box('❌  CANCELLED')}")
        return

    # Upload option callbacks
    state = user_states.get(user_id)
    if not state:
        await cb.answer("⚠️ Session expired. Send URL again.", show_alert=True)
        return

    url = state["url"]
    filename = state["filename"]
    orig_msg_id = state.get("original_message_id")

    if data == "up_def":
        user_states.pop(user_id, None)
        await cb.message.delete()
        await _process_download(
            client, cb.message, url, custom_filename=filename,
            original_message_id=orig_msg_id,
            user=cb.from_user,
        )

    elif data == "up_ren":
        user_states[user_id] = {
            "action": "awaiting_rename",
            "url": url,
            "original_filename": filename,
            "original_message_id": orig_msg_id,
        }
        await cb.message.edit_text(
            f"{_box('✏️  RENAME FILE')}\n\n"
            f"Current: <code>{filename}</code>\n\n"
            f"<i>Send the new filename now:</i>"
        )


# ─── Core download → upload pipeline ──────────────────────────────────────────
# ─── Core download → upload pipeline ──────────────────────────────────────────
async def _process_download(
    client: Client,
    message: Message,
    url: str,
    custom_filename: str | None = None,
    original_message_id: int | None = None,
    user=None,
):
    import random
    import string
    
    if user is None:
        user = message.from_user
    user_id = user.id
    reply_id = original_message_id or message.id
    task = asyncio.current_task()
    if task:
        active_tasks.setdefault(user_id, []).append(task)

    task_id = "task_" + "".join(random.choices(string.ascii_letters + string.digits, k=11))
    bot_name = client.me.first_name if (hasattr(client, "me") and client.me) else "Bot"
    
    role = await get_user_role(user_id)
    if role == "owner":
        role_str = "👑 Owner"
    elif role == "premium":
        role_str = "🌟 Premium"
    else:
        role_str = "🆓 Free"

    username_str = f"@{user.username}" if user.username else "N/A"
    user_mention = f"<a href='tg://user?id={user_id}'>{user.first_name}</a>"

    status_msg = await client.send_message(
        chat_id=message.chat.id,
        text="🚀 <b>Starting download…</b>",
        reply_to_message_id=reply_id,
    )
    dl_start = time.time()
    local_path: str | None = None
    filename = custom_filename or await get_filename(url)
    success = False

    # Fetch pre-download size if possible
    fsize_pre = await get_file_size(url)
    size_str = file_size_format(fsize_pre) if fsize_pre > 0 else "Unknown"

    # Send Task Started Log to channel
    if config.LOG_CHANNEL:
        task_start_log = (
            f"🚀 Task Started For bot {bot_name}\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"👤 User: {user_mention}\n"
            f"🆔 ID: <code>{user_id}</code>\n"
            f"📝 Username: {username_str}\n"
            f"👤 Role: <b>{role_str}</b>\n"
            f"📁 File Name: <code>{filename}</code>\n"
            f"🌐 URL: <code>{url}</code>\n"
            f"Size: <code>{size_str}</code>\n"
            f"🔑 Task ID: <code>{task_id}</code>"
        )
        try:
            await client.send_message(config.LOG_CHANNEL, task_start_log)
        except Exception as le:
            logger.warning("Failed to send task start log: %s", le)

    try:
        logger.info(
            "DOWNLOAD START │ user=%s name=%s file=%s url=%s task_id=%s",
            user_id, user.first_name, filename, url, task_id,
        )

        # Download
        local_path = await async_download_file(
            url, filename,
            progress=progress,
            progress_args=progressArgs("Downloading", status_msg, dl_start),
        )

        fsize = os.path.getsize(local_path)
        dl_time = time.time() - dl_start
        dl_speed = file_size_format(fsize / dl_time) if dl_time > 0 else "N/A"
        logger.info(
            "DOWNLOAD DONE │ user=%s file=%s size=%s time=%.2fs speed=%s/s task_id=%s",
            user_id, filename, file_size_format(fsize), dl_time, dl_speed, task_id,
        )

        await status_msg.edit_text("📤 <b>Download complete! Uploading…</b>")

        ul_start = time.time()
        caption = (
            f"{_box('✅  UPLOAD COMPLETE')}\n\n"
            f"📁 <b>Name:</b>       <code>{filename}</code>\n"
            f"📦 <b>Size:</b>       <code>{file_size_format(fsize)}</code>\n"
            f"⬇️ <b>Download:</b>   <code>{dl_time:.1f}s</code> @ <code>{dl_speed}/s</code>"
        )

        is_video = filename.lower().endswith(VIDEO_EXTENSIONS)

        if is_video:
            await client.send_video(
                chat_id=message.chat.id,
                video=local_path,
                caption=caption,
                progress=progress,
                progress_args=progressArgs("Uploading", status_msg, ul_start),
                reply_to_message_id=reply_id,
                supports_streaming=True,
                duration=0,
                width=0,
                height=0,
            )
        else:
            await client.send_document(
                chat_id=message.chat.id,
                document=local_path,
                caption=caption,
                progress=progress,
                progress_args=progressArgs("Uploading", status_msg, ul_start),
                reply_to_message_id=reply_id,
            )

        ul_time = time.time() - ul_start
        ul_speed = file_size_format(fsize / ul_time) if ul_time > 0 else "N/A"
        logger.info(
            "UPLOAD DONE │ user=%s file=%s time=%.2fs speed=%s/s task_id=%s",
            user_id, filename, ul_time, ul_speed, task_id,
        )
        await status_msg.delete()
        success = True

        # Save mapping to DB
        try:
            await register_download(filename, user_id, user.first_name, url)
        except Exception as dbe:
            logger.warning("Failed to register download in DB: %s", dbe)

        # Send Task Finished Log to channel
        if config.LOG_CHANNEL:
            task_finish_log = (
                f"🚀 Task Finished For bot {bot_name}\n"
                f"━━━━━━━━━━━━━━\n\n"
                f"👤 User: {user_mention}\n"
                f"🆔 ID: <code>{user_id}</code>\n"
                f"📝 Username: {username_str}\n"
                f"👤 Role: <b>{role_str}</b>\n"
                f"📁 File Name: <code>{filename}</code>\n"
                f"🌐 URL: <code>{url}</code>\n"
                f"Size: <code>{file_size_format(fsize)}</code>\n"
                f"⏱️ Time: <code>{dl_time + ul_time:.1f}s</code> (DL: <code>{dl_time:.1f}s</code> | UL: <code>{ul_time:.1f}s</code>)\n"
                f"🔑 Task ID: <code>{task_id}</code>"
            )
            try:
                await client.send_message(config.LOG_CHANNEL, task_finish_log)
            except Exception as le:
                logger.warning("Failed to send task finish log: %s", le)

    except asyncio.CancelledError:
        logger.info("Task cancelled │ user=%s task_id=%s", user_id, task_id)
        try:
            await status_msg.edit_text(f"{_box('❌  CANCELLED')}")
        except Exception:
            pass

        # Send Task Cancelled Log to channel
        if config.LOG_CHANNEL:
            task_cancel_log = (
                f"🚀 Task Cancelled For bot {bot_name}\n"
                f"━━━━━━━━━━━━━━\n\n"
                f"👤 User: {user_mention}\n"
                f"🆔 ID: <code>{user_id}</code>\n"
                f"📝 Username: {username_str}\n"
                f"👤 Role: <b>{role_str}</b>\n"
                f"📁 File Name: <code>{filename}</code>\n"
                f"🌐 URL: <code>{url}</code>\n"
                f"🔑 Task ID: <code>{task_id}</code>"
            )
            try:
                await client.send_message(config.LOG_CHANNEL, task_cancel_log)
            except Exception as le:
                logger.warning("Failed to send task cancel log: %s", le)

    except Exception as e:
        logger.error("Upload failed │ user=%s err=%s task_id=%s", user_id, e, task_id, exc_info=True)
        try:
            await status_msg.edit_text(
                f"{_box('❌  TASK FAILED')}\n\n<code>{e}</code>"
            )
        except Exception:
            pass

        # Send Task Failed Log to channel
        if config.LOG_CHANNEL:
            task_fail_log = (
                f"🚀 Task Failed For bot {bot_name}\n"
                f"━━━━━━━━━━━━━━\n\n"
                f"👤 User: {user_mention}\n"
                f"🆔 ID: <code>{user_id}</code>\n"
                f"📝 Username: {username_str}\n"
                f"👤 Role: <b>{role_str}</b>\n"
                f"📁 File Name: <code>{filename}</code>\n"
                f"🌐 URL: <code>{url}</code>\n"
                f"❌ Error: <code>{str(e)}</code>\n"
                f"🔑 Task ID: <code>{task_id}</code>"
            )
            try:
                await client.send_message(config.LOG_CHANNEL, task_fail_log)
            except Exception as le:
                logger.warning("Failed to send task fail log: %s", le)

    finally:
        if task and user_id in active_tasks and task in active_tasks[user_id]:
            active_tasks[user_id].remove(task)
        if not success and local_path and os.path.isfile(local_path):
            await delete_file(local_path)
            logger.debug("Cleaned temp file: %s", local_path)


# ─── Owner-Only Command Handlers & Files Manager ──────────────────────────────

async def show_files_page(message: Message, page: int, reply=False):
    import os
    from helpers.utils import file_size_format
    
    files = []
    if os.path.exists("downloads"):
        for f in os.listdir("downloads"):
            path = os.path.join("downloads", f)
            if os.path.isfile(path):
                files.append(f)
        files.sort(key=lambda x: os.path.getmtime(os.path.join("downloads", x)), reverse=True)
        
    total_files = len(files)
    if total_files == 0:
        text = "📂 <b>No downloaded files available in downloads folder.</b>"
        if reply:
            await message.reply_text(text, reply_to_message_id=message.id)
        else:
            await message.edit_text(text)
        return
        
    files_per_page = 5
    total_pages = (total_files + files_per_page - 1) // files_per_page
    page = max(0, min(total_pages - 1, page))
    
    start_idx = page * files_per_page
    end_idx = min(start_idx + files_per_page, total_files)
    
    keyboard = []
    for idx in range(start_idx, end_idx):
        fname = files[idx]
        keyboard.append([InlineKeyboardButton(f"📄 {fname[:24]}...", callback_data=f"fsel:{idx}:{page}")])
        
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"fpage:{page-1}"))
    nav_buttons.append(InlineKeyboardButton(f"Page {page+1}/{total_pages}", callback_data="fnoop"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("Next ➡️", callback_data=f"fpage:{page+1}"))
        
    keyboard.append(nav_buttons)
    keyboard.append([InlineKeyboardButton("🗑 Delete All Files", callback_data="fdelall")])
    keyboard.append([InlineKeyboardButton("❌ Close Menu", callback_data="fclose")])
    
    text = f"📂 <b>Downloaded Files Manager</b>\nTotal files: <code>{total_files}</code>"
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if reply:
        await message.reply_text(text, reply_markup=reply_markup, reply_to_message_id=message.id)
    else:
        await message.edit_text(text, reply_markup=reply_markup)


async def show_file_details(cb: CallbackQuery, idx: int, page: int):
    import os
    files = []
    if os.path.exists("downloads"):
        for f in os.listdir("downloads"):
            path = os.path.join("downloads", f)
            if os.path.isfile(path):
                files.append(f)
        files.sort(key=lambda x: os.path.getmtime(os.path.join("downloads", x)), reverse=True)
        
    if idx >= len(files):
        return await cb.answer("❌ File no longer exists.", show_alert=True)
        
    fname = files[idx]
    path = os.path.join("downloads", fname)
    
    info = await get_download_info(fname)
    user_id_details = f"<code>{info.get('user_id', 'N/A')}</code> (@{info.get('username', 'N/A')})" if info.get('user_id') else "N/A"
    creation_date = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(os.path.getctime(path)))
    fsize = file_size_format(os.path.getsize(path))
    
    text = (
        f"📄 <b>File Details</b>\n"
        f"━━━━━━━━━━━━━━\n\n"
        f"📁 <b>Name:</b> <code>{fname}</code>\n"
        f"📦 <b>Size:</b> <code>{fsize}</code>\n"
        f"🕒 <b>Created:</b> <code>{creation_date}</code>\n"
        f"👤 <b>Downloaded By User:</b> {user_id_details}\n"
    )
    
    keyboard = [
        [
            InlineKeyboardButton("📤 Send File", callback_data=f"fsend:{idx}:{page}"),
            InlineKeyboardButton("❌ Delete File", callback_data=f"fdel:{idx}:{page}")
        ],
        [
            InlineKeyboardButton("🔙 Back to List", callback_data=f"fpage:{page}")
        ]
    ]
    await cb.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


@bot.on_message(filters.command("files") & filters.private)
@registration_required
async def files_command(client: Client, message: Message):
    if message.from_user.id != config.OWNER_ID:
        return await message.reply_text("⛔ <b>Owner-only command.</b>", reply_to_message_id=message.id)
    await show_files_page(message, 0, reply=True)


@bot.on_message(filters.command("ping") & filters.private)
@registration_required
async def ping_command(client: Client, message: Message):
    if message.from_user.id != config.OWNER_ID:
        return await message.reply_text("⛔ <b>Owner-only command.</b>", reply_to_message_id=message.id)
    
    t0 = time.time()
    msg = await message.reply_text("⚡", reply_to_message_id=message.id)
    ping_ms = round((time.time() - t0) * 1000, 2)
    await msg.edit_text(f"🏓 <b>Pong!</b> Latency: <code>{ping_ms} ms</code>")


@bot.on_message(filters.command("ban") & filters.private)
@registration_required
async def ban_command(client: Client, message: Message):
    if message.from_user.id != config.OWNER_ID:
        return await message.reply_text("⛔ <b>Owner-only command.</b>", reply_to_message_id=message.id)
        
    target_id = None
    target_name = ""
    reason = ""
    
    if message.reply_to_message:
        target_id = message.reply_to_message.from_user.id
        target_name = message.reply_to_message.from_user.first_name
        reason = " ".join(message.command[1:]) if len(message.command) > 1 else "No reason provided."
    else:
        if len(message.command) < 2:
            return await message.reply_text("⚠️ <b>Usage:</b> <code>/ban &lt;user_id/username&gt; [reason]</code> or reply to a user message with <code>/ban [reason]</code>", reply_to_message_id=message.id)
        target = message.command[1]
        reason = " ".join(message.command[2:]) if len(message.command) > 2 else "No reason provided."
        user_data = await get_user_by_id_or_username(target)
        if not user_data:
            return await message.reply_text("❌ <b>User not found in database.</b>", reply_to_message_id=message.id)
        target_id = user_data["user_id"]
        target_name = user_data["first_name"]

    if target_id == config.OWNER_ID:
        return await message.reply_text("❌ <b>Cannot ban the owner.</b>", reply_to_message_id=message.id)

    await ban_user(target_id, reason)
    
    try:
        await client.send_message(target_id, f"⛔ <b>You have been banned from this bot.</b>\nReason: <code>{reason}</code>")
        user_notified = "✅ User Notified"
    except Exception as e:
        user_notified = f"❌ User Notification Failed ({e})"
        
    owner_msg = (
        f"⛔ <b>User Ban Event</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 <b>User:</b> <a href='tg://user?id={target_id}'>{target_name}</a>\n"
        f"🆔 <b>ID:</b> <code>{target_id}</code>\n"
        f"📝 <b>Reason:</b> <code>{reason}</code>\n"
        f"📢 <b>Status:</b> {user_notified}"
    )
    await client.send_message(config.OWNER_ID, owner_msg)
    if config.LOG_CHANNEL:
        await send_event_log(client, "USER_BAN", target_id, target_name, f"Banned by admin. Reason: {reason}")
    await message.reply_text(f"✅ <b>User successfully banned.</b>", reply_to_message_id=message.id)


@bot.on_message(filters.command("unban") & filters.private)
@registration_required
async def unban_command(client: Client, message: Message):
    if message.from_user.id != config.OWNER_ID:
        return await message.reply_text("⛔ <b>Owner-only command.</b>", reply_to_message_id=message.id)
        
    target_id = None
    target_name = ""
    
    if message.reply_to_message:
        target_id = message.reply_to_message.from_user.id
        target_name = message.reply_to_message.from_user.first_name
    else:
        if len(message.command) < 2:
            return await message.reply_text("⚠️ <b>Usage:</b> <code>/unban &lt;user_id/username&gt;</code> or reply with <code>/unban</code>", reply_to_message_id=message.id)
        target = message.command[1]
        user_data = await get_user_by_id_or_username(target)
        if not user_data:
            return await message.reply_text("❌ <b>User not found in database.</b>", reply_to_message_id=message.id)
        target_id = user_data["user_id"]
        target_name = user_data["first_name"]

    await unban_user(target_id)
    
    try:
        await client.send_message(target_id, "🎉 <b>Your ban has been lifted. You can now use the bot again.</b>")
        user_notified = "✅ User Notified"
    except Exception as e:
        user_notified = f"❌ User Notification Failed ({e})"
        
    owner_msg = (
        f"🎉 <b>User Unban Event</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 <b>User:</b> <a href='tg://user?id={target_id}'>{target_name}</a>\n"
        f"🆔 <b>ID:</b> <code>{target_id}</code>\n"
        f"📢 <b>Status:</b> {user_notified}"
    )
    await client.send_message(config.OWNER_ID, owner_msg)
    if config.LOG_CHANNEL:
        await send_event_log(client, "USER_UNBAN", target_id, target_name, "Unbanned by admin.")
    await message.reply_text(f"✅ <b>User successfully unbanned.</b>", reply_to_message_id=message.id)


@bot.on_message(filters.command("restart") & filters.private)
@registration_required
async def restart_command(client: Client, message: Message):
    if message.from_user.id != config.OWNER_ID:
        return await message.reply_text("⛔ <b>Owner-only command.</b>", reply_to_message_id=message.id)
        
    await message.reply_text("🔄 <b>Restarting bot...</b>", reply_to_message_id=message.id)
    if config.LOG_CHANNEL:
        await send_event_log(client, "BOT_RESTART", message.from_user.id, message.from_user.first_name, "Restart triggered by Admin.")
    await asyncio.sleep(1)
    os.execv(sys.executable, [sys.executable] + sys.argv)


@bot.on_message(filters.command("shell") & filters.private)
@registration_required
async def shell_command(client: Client, message: Message):
    if message.from_user.id != config.OWNER_ID:
        return await message.reply_text("⛔ <b>Owner-only command.</b>", reply_to_message_id=message.id)
        
    if len(message.command) < 2:
        return await message.reply_text("⚠️ <b>Usage:</b> <code>/shell &lt;command&gt;</code>", reply_to_message_id=message.id)
        
    cmd = message.text.split(maxsplit=1)[1]
    msg = await message.reply_text("⚙️ <b>Executing...</b>", reply_to_message_id=message.id)
    
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        
        out = stdout.decode().strip()
        err = stderr.decode().strip()
        
        res = ""
        if out:
            res += f"<b>Output:</b>\n<pre>{out}</pre>\n"
        if err:
            res += f"<b>Error:</b>\n<pre>{err}</pre>\n"
            
        if not res:
            res = "✅ <b>Command executed with no output.</b>"
            
        if len(res) > 4000:
            with open("shell_output.txt", "w", encoding="utf-8") as f:
                f.write(f"Command: {cmd}\n\nSTDOUT:\n{out}\n\nSTDERR:\n{err}")
            await message.reply_document("shell_output.txt", caption="📄 Shell Output (Truncated)")
            os.remove("shell_output.txt")
            await msg.delete()
        else:
            await msg.edit_text(res)
            
    except Exception as e:
        await msg.edit_text(f"❌ <b>Execution failed:</b> <code>{e}</code>")


@bot.on_message(filters.command("logs") & filters.private)
@registration_required
async def logs_command(client: Client, message: Message):
    if message.from_user.id != config.OWNER_ID:
        return await message.reply_text("⛔ <b>Owner-only command.</b>", reply_to_message_id=message.id)
    
    if not os.path.exists("bot.log"):
        return await message.reply_text("❌ <b>Log file not found.</b>", reply_to_message_id=message.id)
        
    await message.reply_document(
        document="bot.log",
        file_name="log.txt",
        caption="📋 <b>Bot Logs</b>",
        reply_to_message_id=message.id
    )


@bot.on_message(filters.command("speedtest") & filters.private)
@registration_required
async def speedtest_command(client: Client, message: Message):
    if message.from_user.id != config.OWNER_ID:
        return await message.reply_text("⛔ <b>Owner-only command.</b>", reply_to_message_id=message.id)
        
    msg = await message.reply_text("⚡ <b>Running Speedtest... Please wait.</b>", reply_to_message_id=message.id)
    try:
        res = await run_speedtest()
        
        dl_mbps = res["download"] / 1_000_000
        ul_mbps = res["upload"] / 1_000_000
        ping = res["ping"]
        server = res["server"]
        client_isp = res["client"]
        
        text = (
            f"🚀 <b>Speedtest Results</b>\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"⬇️ <b>Download:</b> <code>{dl_mbps:.2f} Mbps</code>\n"
            f"⬆️ <b>Upload:</b> <code>{ul_mbps:.2f} Mbps</code>\n"
            f"🔹 <b>Ping:</b> <code>{ping} ms</code>\n\n"
            f"🖥️ <b>Server:</b> <code>{server}</code>\n"
            f"👤 <b>Client:</b> <code>{client_isp}</code>"
        )
        await msg.edit_text(text)
    except Exception as e:
        logger.error("Speedtest error: %s", e)
        await msg.edit_text(f"❌ <b>Speedtest failed:</b> <code>{e}</code>")


@bot.on_message(filters.command("promote") & filters.private)
@registration_required
async def promote_command(client: Client, message: Message):
    if message.from_user.id != config.OWNER_ID:
        return await message.reply_text("⛔ <b>Owner-only command.</b>", reply_to_message_id=message.id)
        
    target_id = None
    target_name = ""
    
    if message.reply_to_message:
        target_id = message.reply_to_message.from_user.id
        target_name = message.reply_to_message.from_user.first_name
    else:
        if len(message.command) < 2:
            return await message.reply_text("⚠️ <b>Usage:</b> <code>/promote &lt;user_id/username&gt;</code> or reply with <code>/promote</code>", reply_to_message_id=message.id)
        target = message.command[1]
        user_data = await get_user_by_id_or_username(target)
        if not user_data:
            return await message.reply_text("❌ <b>User not found in database.</b>", reply_to_message_id=message.id)
        target_id = user_data["user_id"]
        target_name = user_data["first_name"]

    await set_user_role(target_id, "premium")
    
    try:
        user_msg = (
            f"🎉 <b>Premium Membership Activated!</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"Congratulations! You have been promoted to <b>Premium User</b>.\n"
            f"You now have multiple concurrent tasks support (limit: {config.PREMIUM_LIMIT})."
        )
        await client.send_message(target_id, user_msg)
        user_notified = "✅ User Notified"
    except Exception as e:
        user_notified = f"❌ User Notification Failed ({e})"
        
    owner_msg = (
        f"👑 <b>Premium Promotion Event</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 <b>User:</b> <a href='tg://user?id={target_id}'>{target_name}</a>\n"
        f"🆔 <b>ID:</b> <code>{target_id}</code>\n"
        f"🔑 <b>Role:</b> Premium\n"
        f"📢 <b>Status:</b> {user_notified}"
    )
    await client.send_message(config.OWNER_ID, owner_msg)
    if config.LOG_CHANNEL:
        await send_event_log(client, "PREMIUM_PROMOTION", target_id, target_name, "Promoted to Premium.")
    await message.reply_text(f"✅ <b>Premium added successfully for {target_name}.</b>", reply_to_message_id=message.id)


@bot.on_message(filters.command("demote") & filters.private)
@registration_required
async def demote_command(client: Client, message: Message):
    if message.from_user.id != config.OWNER_ID:
        return await message.reply_text("⛔ <b>Owner-only command.</b>", reply_to_message_id=message.id)
        
    target_id = None
    target_name = ""
    
    if message.reply_to_message:
        target_id = message.reply_to_message.from_user.id
        target_name = message.reply_to_message.from_user.first_name
    else:
        if len(message.command) < 2:
            return await message.reply_text("⚠️ <b>Usage:</b> <code>/demote &lt;user_id/username&gt;</code> or reply with <code>/demote</code>", reply_to_message_id=message.id)
        target = message.command[1]
        user_data = await get_user_by_id_or_username(target)
        if not user_data:
            return await message.reply_text("❌ <b>User not found in database.</b>", reply_to_message_id=message.id)
        target_id = user_data["user_id"]
        target_name = user_data["first_name"]

    await set_user_role(target_id, "free")
    
    try:
        user_msg = (
            f"⚠️ <b>Premium Status Revoked</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"Your premium access has been removed by an administrator. "
            f"You have been demoted back to a regular free member."
        )
        await client.send_message(target_id, user_msg)
        user_notified = "✅ User Notified"
    except Exception as e:
        user_notified = f"❌ User Notification Failed ({e})"
        
    owner_msg = (
        f"ℹ️ <b>Premium Demotion Event</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 <b>User:</b> <a href='tg://user?id={target_id}'>{target_name}</a>\n"
        f"🆔 <b>ID:</b> <code>{target_id}</code>\n"
        f"🔑 <b>Role:</b> Free\n"
        f"📢 <b>Status:</b> {user_notified}"
    )
    await client.send_message(config.OWNER_ID, owner_msg)
    if config.LOG_CHANNEL:
        await send_event_log(client, "PREMIUM_DEMOTION", target_id, target_name, "Demoted back to Free.")
    await message.reply_text(f"✅ <b>Premium removed successfully for {target_name}.</b>", reply_to_message_id=message.id)


if __name__ == "__main__":
    import glob
    for d in ("downloads", "temp", "data"):
        os.makedirs(d, exist_ok=True)

    # Clean up stale session files in data folder
    for session_file in glob.glob(os.path.join("data", "URLUploaderBot.session*")):
        try:
            os.remove(session_file)
            logger.info("FreshStart │ Removed stale session file: %s", session_file)
        except Exception as e:
            logger.warning("FreshStart │ Failed to remove session file %s: %s", session_file, e)

    logger.info("🚀 Starting URLUploader Bot v%s…", BOT_VERSION)

    async def main():
        # Pre-cleanup old downloads
        loop.create_task(cleanup_old_downloads())

        logger.info("Connecting to Telegram…")
        await bot.start()

        # Clear webhooks via Bot API (drops pending updates from Telegram)
        import aiohttp
        try:
            url = f"https://api.telegram.org/bot{config.BOT_TOKEN}/deleteWebhook?drop_pending_updates=true"
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    res_json = await resp.json()
                    if res_json.get("ok"):
                        logger.info("Webhooks cleared via Telegram Bot API (drop_pending_updates=True).")
                    else:
                        logger.warning(f"Failed to clear webhook: {res_json}")
        except Exception as e:
            logger.error(f"Webhook cleanup failed: {e}")

        try:
            t0 = time.time()
            me = await bot.get_me()
            ping_ms = round((time.time() - t0) * 1000, 2)
            startup_time_sec = round(time.time() - BOT_START_TIME, 2)

            total_users = await get_total_users_count()
            # Database check: just loading users
            try:
                await load_users()
                db_status = "✅ Connected"
            except Exception:
                db_status = "❌ Disconnected"

            now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

            startup_text = (
                f"🚀 {me.first_name} Bot Started Successfully\n"
                f"━━━━━━━━━━━━━━\n\n"
                f"Status: 🟢 Online\n"
                f"Ping: {ping_ms} ms\n"
                f"Database: {db_status}\n"
                f"Users: {total_users}\n"
                f"Startup Time: {startup_time_sec} sec\n"
                f"Version: Latest\n"
                f"Time: {now_utc}\n\n"
                f"Ready to receive commands."
            )

            # Send to Owner
            await bot.send_message(config.OWNER_ID, startup_text)
            logger.info("Startup notification sent to owner %s (ping=%sms)", config.OWNER_ID, ping_ms)

            # Send to Log Channel
            if config.LOG_CHANNEL:
                try:
                    await bot.send_message(config.LOG_CHANNEL, startup_text)
                    logger.info("Startup notification sent to log channel %s", config.LOG_CHANNEL)
                except Exception as lce:
                    logger.warning("Failed to send startup log to channel: %s", lce)

        except Exception as e:
            logger.error("Startup notification failed: %s", e)

        # Keep the bot running until a stop signal is received
        from pyrogram import idle
        await idle()
        await bot.stop()
        logger.info("Bot stopped.")

    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        print("\n[!] KeyboardInterrupt received. Stopping bot instantly...")
        import os
        os._exit(0)
