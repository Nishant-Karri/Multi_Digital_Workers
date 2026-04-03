# Installation Guide — Nishant_gastown_replica

Multi-agent orchestrator using Claude Code. No external databases, no custom binaries.

---

## Prerequisites

| Requirement | Version | Check |
|-------------|---------|-------|
| Python | 3.8+ | `python3 --version` |
| Git | any | `git --version` |
| Claude Code | latest | `claude --version` |
| GitHub account | — | `gh auth status` |

### Install Claude Code (if not already installed)

**Mac / Linux:**
```bash
npm install -g @anthropic-ai/claude-code
```

**Windows:**
```powershell
npm install -g @anthropic-ai/claude-code
```

> Need Node.js first? Download from https://nodejs.org (v18+)

---

## Step 1 — Clone the Repo

```bash
git clone https://github.com/Nishant-Karri/Nishant_gastown_replica.git
cd Nishant_gastown_replica
```

---

## Step 2 — Set Your API Key

Claude Code needs your Anthropic API key.

**Mac / Linux:**
```bash
export ANTHROPIC_API_KEY=sk-ant-...
# Make it permanent:
echo 'export ANTHROPIC_API_KEY=sk-ant-...' >> ~/.bashrc   # Linux
echo 'export ANTHROPIC_API_KEY=sk-ant-...' >> ~/.zshrc    # Mac
```

**Windows (PowerShell):**
```powershell
$env:ANTHROPIC_API_KEY = "sk-ant-..."
# Make it permanent:
[System.Environment]::SetEnvironmentVariable("ANTHROPIC_API_KEY", "sk-ant-...", "User")
```

**EC2 / Server (via SSM or SSH):**
```bash
echo 'export ANTHROPIC_API_KEY=sk-ant-...' >> ~/.bashrc
source ~/.bashrc
```

> Get your API key at: https://console.anthropic.com → API Keys

---

## Step 3 — Verify the CLI Works

```bash
python3 ngr.py status
```

Expected output:
```
==================================================
  Nishant_gastown_replica — Status
==================================================
  Inbox (new tasks): 0
  Active tasks:      0
  Blocked tasks:     0
  Completed:         0
  Unread mail:       0
==================================================

  Projects: 4
    · nwt          Nishant_Workflow_Test
    · dashboard    NWT Dashboard
    · gastown_ec2  Gas Town EC2
    · mayor        Mayor Workspace
```

---

## Step 4 — Launch Mayor (Orchestrator)

```bash
cd Nishant_gastown_replica
claude
```

Claude Code will open and automatically read `CLAUDE.md`. You are now the **Mayor**.

Inside the Claude session, run:
```
python3 ngr.py status
```

---

## Step 5 — Add Your Projects (Optional)

Edit `config/projects.json` to register your own projects:

```json
{
  "projects": [
    {
      "id": "myproject",
      "name": "My Project Name",
      "description": "What this project does",
      "repo": "https://github.com/you/myproject",
      "tech_stack": ["Python", "AWS"],
      "default_assignee": "worker",
      "priority": "high"
    }
  ]
}
```

---

## Platform-Specific Notes

### Mac / Linux

Everything works out of the box. No extra steps needed.

```bash
git clone https://github.com/Nishant-Karri/Nishant_gastown_replica.git
cd Nishant_gastown_replica
export ANTHROPIC_API_KEY=sk-ant-...
claude
```

---

### Windows (Local)

```powershell
git clone https://github.com/Nishant-Karri/Nishant_gastown_replica.git
cd Nishant_gastown_replica
$env:ANTHROPIC_API_KEY = "sk-ant-..."
claude
```

---

### EC2 Linux (via SSM)

**1. Install Node.js:**
```bash
curl -fsSL https://rpm.nodesource.com/setup_22.x | sudo bash -
sudo dnf install -y nodejs          # Amazon Linux / RHEL
# or
sudo apt install -y nodejs npm      # Ubuntu / Debian
```

**2. Install Claude Code:**
```bash
npm install -g @anthropic-ai/claude-code
```

**3. Clone and launch:**
```bash
git clone https://github.com/Nishant-Karri/Nishant_gastown_replica.git
cd Nishant_gastown_replica
export ANTHROPIC_API_KEY=sk-ant-...
claude
```

---

### EC2 Windows (via SSM)

**1. Start an SSM session:**
```bash
# On your Mac/local machine:
aws ssm start-session --target i-xxxxxxxxxxxxxxxxx
```

**2. Install Node.js (in the SSM PowerShell session):**
```powershell
Invoke-WebRequest -Uri "https://nodejs.org/dist/v22.14.0/node-v22.14.0-x64.msi" -OutFile "C:\node.msi"
msiexec /i C:\node.msi /quiet /norestart
$env:PATH = [System.Environment]::GetEnvironmentVariable("Path","Machine")
```

**3. Install Claude Code:**
```powershell
npm install -g @anthropic-ai/claude-code
```

**4. Clone and launch:**
```powershell
git clone https://github.com/Nishant-Karri/Nishant_gastown_replica.git
cd Nishant_gastown_replica
$env:ANTHROPIC_API_KEY = "sk-ant-..."
claude
```

---

## Daily Usage

### As Mayor (Orchestrator)

```bash
cd Nishant_gastown_replica
claude
```

Inside Claude, run `python3 ngr.py status` to see the system state, then work from there.

### Common Commands

```bash
# Check overall status
python3 ngr.py status

# See all open tasks
python3 ngr.py tasks list

# Create a new task
python3 ngr.py tasks create --title "Fix the login bug" --project myproject --priority high

# See tasks ready to work
python3 ngr.py tasks ready

# Claim and start a task
python3 ngr.py tasks claim TASK-abc123 --agent worker

# Complete a task
python3 ngr.py tasks complete TASK-abc123 --notes "Fixed by updating auth middleware"

# Send mail between agents
python3 ngr.py mail send worker "Start task TASK-abc123"

# Check your inbox
python3 ngr.py mail inbox

# View run history
python3 ngr.py history
```

### Spawning a Worker (inside Claude as Mayor)

When you need to delegate work, use Claude Code's built-in Agent tool:

```
Spawn a worker for task TASK-abc123
```

Or use the CLI to get the exact spawn command:
```bash
python3 ngr.py spawn worker --task TASK-abc123
```

This prints the Agent tool invocation for you to copy into Claude.

---

## File Structure Reference

```
Nishant_gastown_replica/
├── CLAUDE.md                   ← Auto-loaded by Claude Code (town identity)
├── ngr.py                      ← Main CLI
├── agents/
│   ├── mayor/
│   │   ├── CLAUDE.md           ← Mayor role definition
│   │   └── settings.json       ← Claude hooks (auto-save, startup)
│   ├── worker/CLAUDE.md        ← Worker role definition
│   ├── monitor/CLAUDE.md       ← Monitor role definition
│   └── refinery/CLAUDE.md      ← Refinery role definition
├── config/
│   ├── agents.json             ← Agent registry
│   ├── projects.json           ← Your projects
│   └── routing.json            ← Task routing rules
├── tasks/
│   ├── inbox/                  ← New tasks (JSON files)
│   ├── active/                 ← In-progress tasks
│   └── completed/              ← Done tasks
├── mail/                       ← Inter-agent messages
└── history/                    ← Daily run logs
```

---

## Troubleshooting

**`claude: command not found`**
```bash
npm install -g @anthropic-ai/claude-code
# Then reload your shell or open a new terminal
```

**`python3: command not found`**
```bash
# Mac
brew install python3
# Linux
sudo apt install python3   # Debian/Ubuntu
sudo dnf install python3   # Amazon Linux/RHEL
# Windows
winget install Python.Python.3
```

**`ANTHROPIC_API_KEY not set`**
```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

**Claude Code doesn't load CLAUDE.md automatically**

Make sure you launched `claude` from inside the repo directory:
```bash
cd Nishant_gastown_replica
claude   # ← must be run from here
```

**Tasks not persisting after session**

All state is in JSON files. Commit them to git:
```bash
git add tasks/ mail/ history/
git commit -m "save: session state"
git push
```

---

## Architecture Summary

```
You (Human)
    ↓
  Mayor (Claude Code session in repo root)
    ↓ uses Agent tool
  Workers / Monitor / Refinery (subagent sessions)
    ↓
  ngr.py (task/mail/state management)
    ↓
  JSON files + Git (persistence)
```

No Dolt. No tmux. No custom Go binaries. **Pure Claude.**
