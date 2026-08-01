<h1 align="center">🚀 URLUploader Telegram Bot</h1>

<p align="center">
  <a href="https://github.com/cyberwarden5/urluploaderx/stargazers"><img src="https://img.shields.io/github/stars/cyberwarden5/urluploaderx?color=blue&style=flat" alt="GitHub Repo stars"></a>
  <a href="https://github.com/cyberwarden5/urluploaderx/issues"><img src="https://img.shields.io/github/issues/cyberwarden5/urluploaderx" alt="GitHub issues"></a>
  <a href="https://github.com/cyberwarden5/urluploaderx/pulls"><img src="https://img.shields.io/github/issues-pr/cyberwarden5/urluploaderx" alt="GitHub pull requests"></a>
  <a href="https://github.com/cyberwarden5/urluploaderx/graphs/contributors"><img src="https://img.shields.io/github/contributors/cyberwarden5/urluploaderx?style=flat" alt="GitHub contributors"></a>
</p>

<p align="center">
  <em>URLUploader: An advanced, high-performance Telegram bot script to download files from direct download URLs, extract video screenshot collages, check file sizes, rename files, and log activity with progress indicators.</em>
</p>
<hr>

## ✨ Key Features

- 📥 **Direct URL Upload:** Download direct HTTP/HTTPS files (up to 4GB) and upload directly to Telegram as Video or Document.
- 🎬 **Video Screenshot Generator (`/ss`):** Extract video screenshot frames and generate an aesthetic grid collage from video files or video URLs!
- 👤 **Automatic User Registration:** Persistent JSON storage in `data/users.json` tracking all bot users.
- 📂 **File Manager (`/files`):** Interactive paginated browser for the owner to view details (creation date, user ID), send files directly, or delete them.
- 💾 **Database Separation:** Clean architecture separating `data/users.json` and `data/downloads.json` to store registry information and transaction logs safely.
- 📜 **Log Channel Integration:** Automatically logs all user activities, commands, registrations, and errors to your private Telegram `LOG_CHANNEL`.
- 💻 **Owner Dashboard (`/status` & `/ping`):** View real-time system performance (CPU %, RAM, Storage, Bot Uptime, and Ping latency).
- ⚡ **Multi-threaded Performance:** Asynchronous media handling and throttled progress bars to avoid Telegram flood limits.
- ✏️ **File Renaming:** Rename any file prior to downloading and uploading.

---

## 🛠️ Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure `.env`
Create a `.env` file in the root folder (see `.env.example`):
```env
API_ID=28271744
API_HASH=1df4d2b4dc77dc5fd65622f9d8f6814d
BOT_TOKEN=8075052119:AAFEE8meQKG3Ncp8mj-nu7HbIC841rlg-Rg
OWNER_ID=7647902709
LOG_CHANNEL=-1003336496391
PREMIUM_LIMIT=5
```

### 3. Start Bot
```bash
python main.py
```

---

## 📖 Command Reference

### User Commands
- `/start` - Check registration status and view welcome menu.
- `/help` - View usage guide and options.
- `/ss [count]` - Generate video screenshots & grid collage (Reply to video message or direct video link).
- `/status` - View live server metrics, ping, CPU, RAM, and Disk storage.

### Owner-Only Commands
- `/ping` - Measure bot ping latency.
- `/speedtest` - Run speedtest metric.
- `/files` - Manage downloaded files.
- `/promote` - Promote a user to Premium (allows up to `PREMIUM_LIMIT` concurrent downloads).
- `/demote` - Revoke premium status.
- `/ban` - Ban a user.
- `/unban` - Unban a user.
- `/logs` - Get bot log.txt file.
- `/restart` - Restart bot process.
- `/shell` - Run shell command.

---

## 👥 Author & Credits

- **Name:** Aftab Kabir
- **Telegram Channel:** [@AftabKabir](https://t.me/@AftabKabir)
