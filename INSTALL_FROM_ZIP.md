# Multi_Digital_Workers — Installation from Zip

## Prerequisites

| Requirement | Version | Check |
|-------------|---------|-------|
| Python | 3.11+ | `python3 --version` |
| pip | latest | `pip --version` |
| Claude Code | latest | `npm install -g @anthropic-ai/claude-code` |

---

## Mac / Linux

### Step 1 — Download the zip
Save `Multi_Digital_Workers.zip` to your Desktop from:
- GitHub: `https://github.com/Nishant-Karri/Multi_Digital_Workers`
- Or use the zip file shared with you directly

### Step 2 — Open Terminal and unzip
```bash
cd ~/Desktop
unzip Multi_Digital_Workers.zip
cd MDW_fresh
```

### Step 3 — Check Python version
```bash
python3 --version
# Must be 3.11+
```
If not installed: download from [python.org](https://www.python.org/downloads/)

### Step 4 — Create virtual environment
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### Step 5 — Install dependencies
```bash
pip install -r requirements.txt
```

### Step 6 — Copy credentials template
```bash
cp vault/env.template .env
```

### Step 7 — Verify it works
```bash
python3 mdw.py status
```

### Step 8 — Start Claude Code
```bash
claude
```

---

## Windows (PowerShell)

### Step 1 — Download the zip
Save `Multi_Digital_Workers.zip` to your Desktop

### Step 2 — Open PowerShell and unzip
```powershell
cd $env:USERPROFILE\Desktop
Expand-Archive -Path Multi_Digital_Workers.zip -DestinationPath .
cd MDW_fresh
```

### Step 3 — Check Python version
```powershell
python --version
# Must be 3.11+
```
If not installed: download from [python.org](https://www.python.org/downloads/)

### Step 4 — Create virtual environment
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

> If blocked by execution policy run first:
> ```powershell
> Set-ExecutionPolicy RemoteSigned -Scope CurrentUser
> ```

### Step 5 — Install dependencies
```powershell
pip install -r requirements.txt
```

### Step 6 — Copy credentials template
```powershell
Copy-Item vault\env.template .env
```

### Step 7 — Verify it works
```powershell
python mdw.py status
```

### Step 8 — Start Claude Code
```powershell
claude
```

---

## Windows EC2 via SSM (No RDP)

### Step 1 — Connect via SSM from your local terminal
```bash
aws ssm start-session --target <instance-id>
```

### Step 2 — Load PATH and go to repo
```powershell
$env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine")
Set-Location C:\ngr
```

### Step 3 — Activate environment
```powershell
.venv\Scripts\Activate.ps1
```

### Step 4 — Install dependencies
```powershell
pip install -r requirements.txt
```

### Step 5 — Verify
```powershell
python mdw.py status
```

### Step 6 — Start Claude Code
```powershell
claude
```

---

## Post-Installation — Fill in Credentials

Edit `.env` with your credentials:

```env
# Snowflake
SNOWFLAKE_ACCOUNT=yourorg-accountid
SNOWFLAKE_USER=your_user
SNOWFLAKE_PASSWORD=your_password
SNOWFLAKE_ROLE=SYSADMIN
SNOWFLAKE_WAREHOUSE=COMPUTE_WH
SNOWFLAKE_DATABASE=NWT_DB
SNOWFLAKE_SCHEMA=PUBLIC

# AWS (uses CLI profile — no keys needed if using instance role)
AWS_DEFAULT_REGION=us-east-1

# JIRA
JIRA_URL=https://yourcompany.atlassian.net
JIRA_USER=your.email@company.com
JIRA_TOKEN=your_jira_api_token

# Alerting
TEAMS_WEBHOOK=https://yourcompany.webhook.office.com/...
SLACK_WEBHOOK=https://hooks.slack.com/services/...
```

Then test all connections:
```bash
python3 scripts/test_connections.py   # Mac/Linux
python scripts\test_connections.py    # Windows
```

---

## Quick Reference

| Task | Mac/Linux | Windows |
|------|-----------|---------|
| Activate env | `source .venv/bin/activate` | `.venv\Scripts\Activate.ps1` |
| Check status | `python3 mdw.py status` | `python mdw.py status` |
| Sync JIRA | `python3 mdw.py jira sync` | `python mdw.py jira sync` |
| Run QA | `python3 mdw.py qa run --pipeline <name>` | `python mdw.py qa run --pipeline <name>` |
| Start Claude | `claude` | `claude` |
