# 🐙 Git Version Control & Deployment Guide

This guide details how to initialize git, upload the codebase to your remote repository (e.g., GitHub, GitLab), and push future updates.

---

## 🛠️ Step 1: Initial Repository Setup

If you are setting up the repository for the first time, run these commands inside the root directory (`URLUploader`):

```bash
# Initialize local Git repository
git init

# Configure user identification details (replace with yours)
git config --global user.name "Your Name"
git config --global user.email "your.email@example.com"

# Create a standard .gitignore to avoid pushing API tokens and logs
# Make sure .env, data/, downloads/, temp/, and *.log are inside it
```

Create a `.gitignore` file (if not already present):
```text
# Local configuration & secrets
.env
data/
downloads/
temp/
*.log

# Python cache & Venv
__pycache__/
*.pyc
venv/
```

Add your files, commit them, and connect to your remote repository:

```bash
# Add all tracked files
git add .

# Create initial commit
git commit -m "feat: initial commit for production-ready bot"

# Rename default branch to main
git branch -M main

# Link local repository to your remote Git URL
git remote add origin https://github.com/your-username/your-repo.git

# Force-push initial commit to remote main branch
git push -u origin main
```

---

## 🔄 Step 2: Push Future Code Updates

Whenever you make updates to the code or add new files, run the following sequence to push changes:

```bash
# 1. Pull latest changes from remote (prevents conflicts)
git pull origin main

# 2. Add modified files to staging area
git add .
# Or add specific files:
# git add main.py helpers/db.py

# 3. Create descriptive commit message
git commit -m "feat: added download log DB separation"

# 4. Push updates to Github
git push origin main
```

---

## 📌 Useful Commands

- **Check modified status:**
  ```bash
  git status
  ```
- **View changes line-by-line before committing:**
  ```bash
  git diff
  ```
- **Discard local uncommitted changes to a file:**
  ```bash
  git checkout -- main.py
  ```
- **View commit history logs:**
  ```bash
  git log --oneline -n 10
  ```
