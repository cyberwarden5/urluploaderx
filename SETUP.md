# 🚀 URL Uploader Telegram Bot - Setup & Deployment Guide

This guide details how to configure, run, and deploy the high-performance **URL Uploader Telegram Bot**.

---

## ⚙️ Requirements

- **Python 3.8+** installed
- **FFmpeg** installed (optional, OpenCV will be used for screenshots if FFmpeg is unavailable)
- **Telegram API Credentials** (`API_ID`, `API_HASH`) from [my.telegram.org](https://my.telegram.org)
- **Telegram Bot Token** from [@BotFather](https://t.me/BotFather)

---

## 🛠️ Step 1: Clone & Install Dependencies

```bash
# Clone repository
git clone https://github.com/cyberwarden5/urluploaderx.git
cd urluploaderx

# (Optional) Create virtual environment
python -m venv venv
# Windows activate:
venv\Scripts\activate
# Linux/macOS activate:
source venv/bin/activate

# Install required packages
pip install -r requirements.txt
```

---

## 🔑 Step 2: Configure Environment Variables

Create a `.env` file in the root project directory (or copy from `.env.example`):

```env
API_ID=28271744
API_HASH=1df4d2b4dc77dc5fd65622f9d8f6814d
BOT_TOKEN=8075052119:AAFEE8meQKG3Ncp8mj-nu7HbIC841rlg-Rg
OWNER_ID=7647902709
LOG_CHANNEL=-1003336496391
MAX_FILE_SIZE=4294967296
PREMIUM_LIMIT=5
```

---

## 🎬 Step 3: Run the Bot

Launch the main bot process locally:

```bash
python main.py
```

---

## 🤖 Features & Commands

| Command | User Level | Description |
| :--- | :--- | :--- |
| `/start` | All Users | Registration check & Welcome Menu |
| `/help` | All Users | Full Bot usage guide |
| `/ss [count]` | All Users | Video screenshot collage generator (Reply to video/link) |
| `/status` | All Users | System CPU, RAM, Storage overview & Ping test |
| `/ping` | Owner Only | Measure bot ping latency |
| `/speedtest` | Owner Only | Test system server download/upload bandwidth |
| `/files` | Owner Only | Interactive paginated local files directory browser |
| `/promote` | Owner Only | Promote target user to Premium |
| `/demote` | Owner Only | Demote target user to Free |
| `/ban` | Owner Only | Prevent target user from interacting with the bot |
| `/unban` | Owner Only | Restore bot access to target user |
| `/logs` | Owner Only | Send bot's console execution `log.txt` output |
| `/restart` | Owner Only | Hot-reload bot script and configurations |
| `/shell [cmd]` | Owner Only | Run custom bash/powershell scripts |

---

## 🌐 Production Deployment (Continuous Execution)

To deploy the bot continuously on a Linux cloud server (VPS), use one of the following production execution utilities:

### Method 1: Using TMUX (Terminal Multiplexer)
`tmux` keeps the bot running persistently in a background terminal session even after you disconnect from your VPS terminal:

1. **Install Tmux** (on Debian/Ubuntu systems):
   ```bash
   sudo apt update && sudo apt install tmux -y
   ```

2. **Start a new background tmux session**:
   ```bash
   tmux new -s urluploader
   ```

3. **Activate environment & launch the bot**:
   ```bash
   source venv/bin/activate
   python main.py
   ```

4. **Detach from the tmux session**:
   Press `Ctrl + B`, then release and press `D` to safely detach. Your bot is now running persistently in the background.

5. **Re-attach to the session later**:
   To view progress logs or interact with the terminal again:
   ```bash
   tmux attach -t urluploader
   ```

6. **Kill the session**:
   ```bash
   tmux kill-session -t urluploader
   ```

### Method 2: Systemd Daemon Service
Creating a systemd service is the most resilient approach as it automatically restarts the bot upon system boot or crashes.

1. **Create service file**:
   ```bash
   sudo nano /etc/systemd/system/urluploader.service
   ```

2. **Add Configuration**:
   ```ini
   [Unit]
   Description=URLUploader Telegram Bot Service
   After=network.target

   [Service]
   Type=simple
   User=root
   WorkingDirectory=/root/urluploaderx
   ExecStart=/root/urluploaderx/venv/bin/python main.py
   Restart=always
   RestartSec=3

   [Install]
   WantedBy=multi-user.target
   ```

3. **Reload systemd, start & enable daemon**:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl start urluploader
   sudo systemctl enable urluploader
   ```

4. **Monitor live logs**:
   ```bash
   sudo journalctl -u urluploader -f -n 50
   ```

---

## 👥 Author & Credits

- **Name:** Aftab Kabir
- **Telegram Channel:** [@AftabKabir](https://t.me/@AftabKabir)
