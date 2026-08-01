import os
import json
import time
import asyncio
import logging
from typing import Any

logger = logging.getLogger("URLUploaderBot.DB")

DB_PATH = os.path.join("data", "users.json")
DL_DB_PATH = os.path.join("data", "downloads.json")
_lock = asyncio.Lock()
_dl_lock = asyncio.Lock()


def _ensure_db_exists(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump({}, f, indent=4)


async def load_users() -> dict[str, Any]:
    _ensure_db_exists(DB_PATH)
    async with _lock:
        try:
            with open(DB_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.error("Failed to load users DB: %s — resetting to empty", e)
            return {}


async def save_users(users: dict[str, Any]) -> None:
    _ensure_db_exists(DB_PATH)
    async with _lock:
        tmp_path = DB_PATH + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(users, f, indent=4, ensure_ascii=False)
            os.replace(tmp_path, DB_PATH)
        except OSError as e:
            logger.error("Failed to save users DB: %s", e)
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise


async def load_downloads() -> dict[str, Any]:
    _ensure_db_exists(DL_DB_PATH)
    async with _dl_lock:
        try:
            with open(DL_DB_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.error("Failed to load downloads DB: %s — resetting to empty", e)
            return {}


async def save_downloads(downloads: dict[str, Any]) -> None:
    _ensure_db_exists(DL_DB_PATH)
    async with _dl_lock:
        tmp_path = DL_DB_PATH + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(downloads, f, indent=4, ensure_ascii=False)
            os.replace(tmp_path, DL_DB_PATH)
        except OSError as e:
            logger.error("Failed to save downloads DB: %s", e)
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise


async def is_user_registered(user_id: int) -> bool:
    users = await load_users()
    return str(user_id) in users


async def get_user_role(user_id: int) -> str:
    import config
    if user_id == config.OWNER_ID:
        return "owner"
    users = await load_users()
    uid_str = str(user_id)
    if uid_str in users:
        return users[uid_str].get("role", "free")
    return "free"


async def register_user(user_id: int, first_name: str = "", username: str = "") -> bool:
    users = await load_users()
    uid_str = str(user_id)
    is_new = uid_str not in users

    now = time.strftime("%Y-%m-%d %H:%M:%S")
    if is_new:
        import config
        role = "owner" if user_id == config.OWNER_ID else "free"
        users[uid_str] = {
            "user_id": user_id,
            "first_name": first_name or "Anonymous",
            "username": username or "",
            "role": role,
            "registered_at": now,
            "last_active": now,
            "is_banned": False,
            "ban_reason": "",
        }
        logger.info("New user registered: %s (%s) with role %s", user_id, first_name, role)
    else:
        rec = users[uid_str]
        if first_name:
            rec["first_name"] = first_name
        if username:
            rec["username"] = username
        rec["last_active"] = now
        # Keep role sync
        if "role" not in rec:
            import config
            rec["role"] = "owner" if user_id == config.OWNER_ID else "free"

    await save_users(users)
    return is_new


async def get_user_by_username(username: str) -> Any:
    if not username:
        return None
    username = username.lstrip("@").lower()
    users = await load_users()
    for uid_str, data in users.items():
        if not uid_str.isdigit():
            continue
        if data.get("username", "").lower() == username:
            return data
    return None


async def get_user_by_id_or_username(target: str) -> Any:
    users = await load_users()
    if target.isdigit():
        return users.get(target)
    return await get_user_by_username(target)


async def set_user_role(user_id: int, role: str) -> bool:
    users = await load_users()
    uid_str = str(user_id)
    if uid_str not in users:
        return False
    users[uid_str]["role"] = role
    await save_users(users)
    return True


async def ban_user(user_id: int, reason: str = "") -> bool:
    users = await load_users()
    uid_str = str(user_id)
    if uid_str not in users:
        users[uid_str] = {
            "user_id": user_id,
            "first_name": "Banned User",
            "username": "",
            "role": "free",
            "registered_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "last_active": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
    users[uid_str]["is_banned"] = True
    users[uid_str]["ban_reason"] = reason
    await save_users(users)
    return True


async def unban_user(user_id: int) -> bool:
    users = await load_users()
    uid_str = str(user_id)
    if uid_str in users:
        users[uid_str]["is_banned"] = False
        users[uid_str]["ban_reason"] = ""
        await save_users(users)
        return True
    return False


async def is_user_banned(user_id: int) -> bool:
    import config
    if user_id == config.OWNER_ID:
        return False
    users = await load_users()
    uid_str = str(user_id)
    if uid_str in users:
        return users[uid_str].get("is_banned", False)
    return False


async def register_download(filename: str, user_id: int, username: str, url: str) -> None:
    downloads = await load_downloads()
    downloads[filename] = {
        "user_id": user_id,
        "username": username,
        "url": url,
        "downloaded_at": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    await save_downloads(downloads)


async def get_download_info(filename: str) -> dict:
    downloads = await load_downloads()
    return downloads.get(filename, {})


async def get_total_users_count() -> int:
    users = await load_users()
    return len([uid for uid in users if uid.isdigit()])


async def get_all_user_ids() -> list[int]:
    users = await load_users()
    return [int(uid) for uid in users if uid.isdigit()]
