# Installation Guide — Nishant_gastown_replica on Windows EC2

This document records every step taken to provision a Windows EC2 instance
and install Claude Code + the orchestrator from scratch using AWS SSM (no RDP required).

---

## Environment

| Property | Value |
|----------|-------|
| **Instance ID** | i-0f179d104b19c5dc0 |
| **AMI** | Windows Server 2022 Datacenter (ami-05856bd26dd466893) |
| **Instance type** | t3.large (2 vCPU / 8 GB RAM) |
| **Storage** | 60 GB gp3 |
| **Region** | us-east-1 |
| **Key pair** | gastown-mayor |
| **Security group** | windows-ec2-sg (sg-00da3a58883a68a33) — RDP :3389, WinRM :5986 |
| **SSM Agent** | 3.3.4108.0 (pre-installed on Windows Server 2022 AMI) |
| **Claude Code** | 2.1.92 |

---

## Part 1 — Provision the EC2 Instance

### 1.1 Find the latest Windows Server 2022 AMI

```bash
aws ec2 describe-images \
  --owners amazon \
  --filters "Name=name,Values=Windows_Server-2022-English-Full-Base-*" \
            "Name=state,Values=available" \
  --query 'sort_by(Images,&CreationDate)[-1].{ID:ImageId,Name:Name}' \
  --output json
# → ami-05856bd26dd466893  (Windows_Server-2022-English-Full-Base-2026.03.11)
```

### 1.2 Create a dedicated security group

```bash
# Create group
aws ec2 create-security-group \
  --group-name "windows-ec2-sg" \
  --description "Windows EC2 - RDP access" \
  --vpc-id vpc-0dd7212e5a107c00b

# Allow RDP
aws ec2 authorize-security-group-ingress \
  --group-id sg-00da3a58883a68a33 \
  --protocol tcp --port 3389 --cidr 0.0.0.0/0

# Allow WinRM HTTPS (remote management)
aws ec2 authorize-security-group-ingress \
  --group-id sg-00da3a58883a68a33 \
  --protocol tcp --port 5986 --cidr 0.0.0.0/0
```

### 1.3 Launch the instance

```bash
aws ec2 run-instances \
  --image-id ami-05856bd26dd466893 \
  --instance-type t3.large \
  --key-name gastown-mayor \
  --security-group-ids sg-00da3a58883a68a33 \
  --subnet-id subnet-016d5b47070c5c746 \
  --associate-public-ip-address \
  --block-device-mappings '[{"DeviceName":"/dev/sda1","Ebs":{"VolumeSize":60,"VolumeType":"gp3","DeleteOnTermination":true}}]' \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=windows-claude-ec2},{Key=Project,Value=gastown}]'
# → Instance ID: i-0f179d104b19c5dc0
# → Public IP:   18.207.245.36
```

### 1.4 Wait for instance + SSM agent to come online

```bash
aws ec2 wait instance-running --instance-ids i-0f179d104b19c5dc0

# Verify SSM is reachable (takes ~2-3 min after boot)
aws ssm describe-instance-information \
  --filters "Key=InstanceIds,Values=i-0f179d104b19c5dc0" \
  --query 'InstanceInformationList[0].PingStatus'
# → "Online"
```

---

## Part 2 — Remote Installation via AWS SSM

All commands below are run from your **local machine** using `aws ssm send-command`.
No RDP, no key file needed — SSM tunnels directly into the instance.

### How to run a command remotely

```bash
# Send command
CMD_ID=$(aws ssm send-command \
  --instance-ids i-0f179d104b19c5dc0 \
  --document-name "AWS-RunPowerShellScript" \
  --timeout-seconds 300 \
  --parameters 'commands=["<YOUR POWERSHELL HERE>"]' \
  --query 'Command.CommandId' --output text)

# Poll for result (allow 30-90s per step)
aws ssm get-command-invocation \
  --command-id $CMD_ID \
  --instance-id i-0f179d104b19c5dc0 \
  --query '{Status:Status,Output:StandardOutputContent}'
```

---

### Step 1 — Install Node.js 22 LTS

**Why:** Claude Code is distributed as an npm package and requires Node.js 18+.

```powershell
$url = "https://nodejs.org/dist/v22.14.0/node-v22.14.0-x64.msi"
Invoke-WebRequest -Uri $url -OutFile "$env:TEMP\nodejs.msi" -UseBasicParsing
Start-Process msiexec.exe -Wait -ArgumentList "/I $env:TEMP\nodejs.msi /quiet /norestart"
```

**Result:** Node.js 22.14.0 + npm 10.9.2 installed to `C:\Program Files\nodejs\`

---

### Step 2 — Install Git for Windows

**Why:** Required to clone the orchestrator repo and for `git` operations inside Claude Code.

```powershell
$url = "https://github.com/git-for-windows/git/releases/download/v2.47.0.windows.2/Git-2.47.0.2-64-bit.exe"
Invoke-WebRequest -Uri $url -OutFile "$env:TEMP\git-installer.exe" -UseBasicParsing
Start-Process -Wait "$env:TEMP\git-installer.exe" `
  -ArgumentList "/VERYSILENT /NORESTART /COMPONENTS=icons,assoc,assoc_sh"
```

**Result:** Git 2.47.0 installed to `C:\Program Files\Git\`

---

### Step 3 — Install Python 3.11

**Why:** The orchestrator (`ngr.py`, all integrations) requires Python 3.11+.

```powershell
$url = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
Invoke-WebRequest -Uri $url -OutFile "$env:TEMP\python-installer.exe" -UseBasicParsing
Start-Process -Wait "$env:TEMP\python-installer.exe" `
  -ArgumentList "/quiet InstallAllUsers=1 PrependPath=1 Include_test=0"
```

**Result:** Python 3.11.9 installed, added to system PATH.

---

### Step 4 — Install Claude Code

**Why:** Claude Code is the AI-powered CLI that drives all agent sessions.

```powershell
# Reload PATH so npm is available in this session
$env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine") + ";" +
            [System.Environment]::GetEnvironmentVariable("PATH","User")

npm install -g @anthropic-ai/claude-code
claude --version
```

**Result:** `2.1.92 (Claude Code)` — installed to npm global bin directory.

---

### Step 5 — Clone the Orchestrator + Setup

**Why:** Pulls the full `Nishant_gastown_replica` repo, creates a Python virtual
environment, installs core dependencies, and copies the `.env` template.

```powershell
$env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine") + ";" +
            [System.Environment]::GetEnvironmentVariable("PATH","User")

Set-Location C:\Users\Administrator

# Clone repo
git clone https://github.com/Nishant-Karri/Nishant_gastown_replica.git
Set-Location Nishant_gastown_replica

# Create isolated Python environment
python -m venv .venv

# Install core Python dependencies
.venv\Scripts\pip install --quiet `
  requests cryptography boto3 snowflake-connector-python pytest ruff

# Copy credential template
Copy-Item vault\env.template .env

# Smoke test
.venv\Scripts\python ngr.py status
```

**Result:**
```
==================================================
  Nishant_gastown_replica — Status
==================================================
  Inbox (new tasks): 0
  Active tasks:      0
  Completed:         0
==================================================
```

---

## Part 3 — First-Time Configuration (do this via RDP)

After the automated install, connect via RDP to complete credential setup.

### 3.1 Connect via RDP

```
Host:     18.207.245.36
Username: Administrator
Password: (AWS Console → EC2 → i-0f179d104b19c5dc0 → Actions → Security → Get Windows password → upload gastown-mayor.pem → Decrypt)
```

### 3.2 Set your Anthropic API key

Open PowerShell as Administrator:

```powershell
# Permanent — survives reboots
[System.Environment]::SetEnvironmentVariable(
  "ANTHROPIC_API_KEY",
  "sk-ant-api03-YOUR_KEY_HERE",
  "Machine"
)
```

### 3.3 Fill in credentials

```powershell
Set-Location C:\Users\Administrator\Nishant_gastown_replica
notepad .env
```

Minimum required fields:

```env
SNOWFLAKE_ACCOUNT=yourorg-accountid
SNOWFLAKE_USER=your_user
SNOWFLAKE_PASSWORD=your_password
SNOWFLAKE_ROLE=SYSADMIN
SNOWFLAKE_WAREHOUSE=COMPUTE_WH
SNOWFLAKE_DATABASE=NWT_DB
JIRA_URL=https://yourcompany.atlassian.net
JIRA_USER=your.email@company.com
JIRA_TOKEN=your_jira_api_token
TEAMS_WEBHOOK=https://yourcompany.webhook.office.com/...
```

### 3.4 Store secrets in vault

```powershell
.venv\Scripts\python vault\vault.py import-env
```

### 3.5 Test all connections

```powershell
.venv\Scripts\python scripts\test_connections.py
```

### 3.6 Start Claude Code

```powershell
Set-Location C:\Users\Administrator\Nishant_gastown_replica
claude
```

---

## Part 4 — Installed Software Summary

| Software | Version | Location |
|----------|---------|----------|
| Windows Server | 2022 Datacenter | — |
| Node.js | 22.14.0 | `C:\Program Files\nodejs\` |
| npm | 10.9.2 | bundled with Node.js |
| Git | 2.47.0 | `C:\Program Files\Git\` |
| Python | 3.11.9 | `C:\Program Files\Python311\` |
| Claude Code | 2.1.92 | npm global bin |
| Repo | latest main | `C:\Users\Administrator\Nishant_gastown_replica\` |
| Python venv | — | `C:\Users\Administrator\Nishant_gastown_replica\.venv\` |

---

## Part 5 — Daily Usage

```powershell
# Navigate to repo
Set-Location C:\Users\Administrator\Nishant_gastown_replica

# Activate Python environment
.venv\Scripts\Activate.ps1

# Start Claude Code
claude

# Common NGR commands
python ngr.py status
python ngr.py jira sync
python ngr.py qa run --pipeline nwt_batch_load
python integrations\reliability.py monitor
python scripts\test_connections.py
```

---

## Part 6 — Re-running Installation on a New Instance

To reproduce this setup on any new Windows EC2:

```bash
# 1. Launch instance (adjust AMI/type/SG as needed)
aws ec2 run-instances --image-id <windows-ami> --instance-type t3.large \
  --key-name gastown-mayor --security-group-ids <sg-id> ...

# 2. Wait for SSM
aws ssm describe-instance-information --filters "Key=InstanceIds,Values=<id>"

# 3. Run each SSM command block from Part 2 in order:
#    Step 1: Node.js  →  Step 2: Git  →  Step 3: Python  →  Step 4: Claude Code  →  Step 5: Clone

# 4. Connect via RDP and complete Part 3 (API key + credentials)
```

Total automated install time: ~5 minutes
