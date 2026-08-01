import os
import re
import time
import logging
import platform
import asyncio
from typing import Optional, Any

import aiohttp
import psutil

logger = logging.getLogger("URLUploaderBot.Utils")

DOWNLOAD_DIR = "downloads"
CHUNK_SIZE = 2 * 1024 * 1024  # 2 MB chunks for faster throughput

PROGRESS_BAR_TEMPLATE = (
    "⚡ <b>{action_title}</b>\n"
    "╔═════════════════╗\n"
    "║ {spin_frame}  <b>Progress:</b> <code>{percentage:.1f}%</code>\n"
    "║ <code>[{bar}]</code>\n"
    "║\n"
    "║ 📦 <b>Done:</b> <code>{current}</code> / <code>{total}</code>\n"
    "║ ⚡ <b>Speed:</b> <code>{speed}/s</code>\n"
    "║ ⏳ <b>ETA:</b> <code>{eta}</code>\n"
    "╚═════════════════╝"
)

SPIN_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

_last_edit: dict[int, float] = {}
_spin_idx: dict[int, int] = {}

# Module-level shared connector for connection pooling
_shared_connector: Optional[aiohttp.TCPConnector] = None


def _get_connector() -> aiohttp.TCPConnector:
    global _shared_connector
    if _shared_connector is None or _shared_connector.closed:
        _shared_connector = aiohttp.TCPConnector(
            limit=100,
            limit_per_host=30,
            ttl_dns_cache=600,
            enable_cleanup_closed=True,
        )
    return _shared_connector


async def cleanup_old_downloads(max_age_hours: int = 2) -> int:
    """Remove download files older than max_age_hours. Returns count removed."""
    removed = 0
    if not os.path.isdir(DOWNLOAD_DIR):
        return removed
    cutoff = time.time() - (max_age_hours * 3600)
    for fname in os.listdir(DOWNLOAD_DIR):
        fpath = os.path.join(DOWNLOAD_DIR, fname)
        try:
            if os.path.isfile(fpath) and os.path.getmtime(fpath) < cutoff:
                os.remove(fpath)
                removed += 1
        except OSError:
            pass
    if removed:
        logger.info("Cleanup: removed %d old download(s)", removed)
    return removed


def progressArgs(
    action: str, message: Any, start_time: float
) -> tuple:
    return (action, message, start_time, PROGRESS_BAR_TEMPLATE, "▰", "▱")


async def async_download_file(
    url: str,
    filename: str,
    progress=None,
    progress_args: tuple = (),
    temp_dir: Optional[str] = None,
) -> str:
    """High-speed async file downloader with 2 MB buffer chunks."""
    download_dir = temp_dir or DOWNLOAD_DIR
    os.makedirs(download_dir, exist_ok=True)
    file_path = os.path.join(download_dir, filename)

    timeout = aiohttp.ClientTimeout(total=None, connect=30, sock_read=120)
    async with aiohttp.ClientSession(
        connector=_get_connector(), timeout=timeout
    ) as session:
        async with session.get(url, headers=HEADERS, allow_redirects=True) as resp:
            if resp.status != 200:
                raise RuntimeError(f"HTTP {resp.status} — download failed for {url}")

            total_size = int(resp.headers.get("content-length", 0))
            downloaded = 0

            with open(file_path, "wb") as fp:
                async for chunk in resp.content.iter_chunked(CHUNK_SIZE):
                    fp.write(chunk)
                    downloaded += len(chunk)
                    if progress and total_size > 0:
                        await progress(downloaded, total_size, *progress_args)

    logger.info("Download complete: %s (%d bytes)", file_path, downloaded)
    return file_path


async def get_file_size(url: str) -> int:
    """Fetch file size via HEAD (falls back to GET)."""
    timeout = aiohttp.ClientTimeout(total=None, connect=15, sock_read=15)
    async with aiohttp.ClientSession(
        connector=_get_connector(), timeout=timeout
    ) as session:
        try:
            async with session.head(url, headers=HEADERS, allow_redirects=True) as resp:
                if resp.status == 200:
                    return int(resp.headers.get("content-length", 0))
        except Exception:
            pass
        async with session.get(url, headers=HEADERS, allow_redirects=True) as resp:
            if resp.status == 200:
                return int(resp.headers.get("content-length", 0))
    return 0


async def get_filename(url: str) -> str:
    """Extract filename from URL or Content-Disposition header."""
    timeout = aiohttp.ClientTimeout(total=None, connect=15, sock_read=15)
    try:
        async with aiohttp.ClientSession(
            connector=_get_connector(), timeout=timeout
        ) as session:
            async with session.head(url, headers=HEADERS, allow_redirects=True) as resp:
                disposition = resp.headers.get("content-disposition", "")
                match = re.findall(r'filename="?([^";]+)"?', disposition)
                if match:
                    return match[0].strip()
    except Exception:
        pass

    clean_url = url.split("?")[0].split("#")[0]
    base = os.path.basename(clean_url)
    if base and "." in base:
        return base
    return "file_download.bin"


def file_size_format(size_bytes: int) -> str:
    if not size_bytes or size_bytes < 0:
        return "0 B"
    units = ("B", "KB", "MB", "GB", "TB")
    size = float(size_bytes)
    for unit in units:
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} PB"


async def delete_file(path: str) -> None:
    try:
        if path and os.path.isfile(path):
            os.remove(path)
            logger.debug("Deleted temp file: %s", path)
    except OSError as e:
        logger.warning("Failed to delete %s: %s", path, e)


def _estimate_time(
    start: float, current: int, total: int
) -> tuple[str, float]:
    elapsed = time.time() - start
    speed = current / elapsed if elapsed > 0 else 0
    remaining = (total - current) / speed if speed > 0 else 0
    return time.strftime("%H:%M:%S", time.gmtime(remaining)), speed


async def progress(
    current: int,
    total: int,
    action: str,
    message: Any,
    start_time: float,
    template: str,
    completed_symbol: str,
    pending_symbol: str,
) -> None:
    """Throttled progress bar edit (1.5 s interval)."""
    if total <= 0:
        return

    msg_id = message.id
    now = time.time()
    if msg_id in _last_edit and (now - _last_edit[msg_id]) < 1.5 and current < total:
        return
    _last_edit[msg_id] = now

    idx = _spin_idx.get(msg_id, 0)
    spin_frame = SPIN_FRAMES[idx % len(SPIN_FRAMES)]
    _spin_idx[msg_id] = idx + 1

    pct = (current / total) * 100
    filled = int((pct * 13) / 100)
    bar = completed_symbol * filled + pending_symbol * (13 - filled)
    eta_str, speed = _estimate_time(start_time, current, total)

    try:
        text = template.format(
            action_title=action.upper(),
            spin_frame=spin_frame,
            percentage=pct,
            bar=bar,
            current=file_size_format(current),
            total=file_size_format(total),
            speed=file_size_format(speed),
            eta=eta_str,
        )
        from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Cancel Task", callback_data="cancel_task")
        ]])
        await message.edit_text(text, reply_markup=kb)
    except Exception as e:
        logger.error(f"Failed to edit progress status message: {e}")


async def get_system_status() -> dict[str, Any]:
    """Non-blocking system stats collection."""

    def _collect() -> dict[str, Any]:
        cpu = psutil.cpu_percent(interval=0.3)
        cpu_count = psutil.cpu_count(logical=True)
        ram = psutil.virtual_memory()
        swap = psutil.swap_memory()
        if platform.system() == "Windows":
            drive = os.getenv("SystemDrive", "C:") + os.sep
        else:
            drive = "/"
        disk = psutil.disk_usage(drive)
        # Count cached download files
        dl_count = 0
        if os.path.isdir(DOWNLOAD_DIR):
            try:
                dl_count = len([f for f in os.listdir(DOWNLOAD_DIR) if os.path.isfile(os.path.join(DOWNLOAD_DIR, f))])
            except OSError:
                pass
        return {
            "cpu": cpu,
            "cpu_count": cpu_count,
            "ram_usage": ram.percent,
            "ram_used": file_size_format(ram.used),
            "ram_total": file_size_format(ram.total),
            "swap_usage": f"{swap.percent}% ({file_size_format(swap.used)} / {file_size_format(swap.total)})" if swap.total else "N/A",
            "disk_usage": disk.percent,
            "disk_used": file_size_format(disk.used),
            "disk_total": file_size_format(disk.total),
            "download_count": dl_count,
            "python": platform.python_version(),
            "platform": platform.system(),
        }

    return await asyncio.get_event_loop().run_in_executor(None, _collect)


async def run_speedtest() -> dict[str, Any]:
    """Runs speedtest-cli in a non-blocking thread executor."""
    def _run():
        import speedtest
        s = speedtest.Speedtest()
        s.get_best_server()
        s.download(threads=None)
        s.upload(threads=None)
        results = s.results.dict()
        return {
            "download": results["download"],  # in bits/sec
            "upload": results["upload"],      # in bits/sec
            "ping": results["ping"],          # ms
            "server": results["server"]["sponsor"] + " (" + results["server"]["name"] + ")",
            "client": results["client"]["ip"] + " (" + results["client"]["isp"] + ")"
        }
    return await asyncio.get_event_loop().run_in_executor(None, _run)
