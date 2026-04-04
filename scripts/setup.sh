#!/usr/bin/env bash
# scripts/setup.sh — First-time setup for Nishant_gastown_replica
# Run: bash scripts/setup.sh

set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

ok()   { echo -e "${GREEN}  ✓${NC} $1"; }
warn() { echo -e "${YELLOW}  ⚠${NC} $1"; }
fail() { echo -e "${RED}  ✗${NC} $1"; exit 1; }
step() { echo -e "\n${YELLOW}── $1${NC}"; }

echo ""
echo "  Nishant_gastown_replica — Setup"
echo "  ================================"

# ── Python version ────────────────────────────────────────────────────────
step "Checking Python"
PY=$(python3 --version 2>&1 | grep -oE '[0-9]+\.[0-9]+' | head -1)
MAJOR=$(echo "$PY" | cut -d. -f1)
MINOR=$(echo "$PY" | cut -d. -f2)
if [ "$MAJOR" -lt 3 ] || { [ "$MAJOR" -eq 3 ] && [ "$MINOR" -lt 11 ]; }; then
  fail "Python 3.11+ required (found $PY). Install from python.org or via pyenv."
fi
ok "Python $PY"

# ── Virtual environment ───────────────────────────────────────────────────
step "Setting up virtual environment"
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
  ok "Created .venv"
else
  ok ".venv already exists"
fi
source .venv/bin/activate
ok "Activated .venv"

# ── Dependencies ──────────────────────────────────────────────────────────
step "Installing core dependencies"
pip install --quiet --upgrade pip
pip install --quiet requests cryptography boto3 snowflake-connector-python pytest ruff
ok "Core dependencies installed"
echo "  (Full install: pip install -r requirements.txt)"

# ── .env file ─────────────────────────────────────────────────────────────
step "Credential setup"
if [ ! -f ".env" ]; then
  cp vault/env.template .env
  warn ".env created from template — fill in your credentials before running"
else
  ok ".env already exists"
fi

# ── Vault init ────────────────────────────────────────────────────────────
step "Vault initialization"
python3 vault/vault.py init 2>/dev/null && ok "Vault initialized" || warn "Vault init skipped (already exists or no local backend needed)"

# ── Observability snapshots ───────────────────────────────────────────────
step "Initializing observability baselines"
mkdir -p observability/snapshots observability/runs
if [ ! -f "observability/snapshots/row_counts.json" ]; then
  echo "{}" > observability/snapshots/row_counts.json
  ok "Created empty row_counts.json baseline"
else
  ok "row_counts.json already exists"
fi
if [ ! -f "observability/snapshots/data_drift_baseline.json" ]; then
  echo "{}" > observability/snapshots/data_drift_baseline.json
  ok "Created empty data_drift_baseline.json"
fi

# ── Runtime dirs ──────────────────────────────────────────────────────────
step "Creating runtime directories"
mkdir -p .runtime tasks/inbox tasks/active tasks/completed tasks/instructions \
         tasks/incidents mail history investigations investigations/fixes \
         qa_artifacts/test_plans qa_artifacts/test_cases qa_artifacts/sample_data \
         qa_artifacts/results qa_artifacts/lineage
ok "Runtime directories ready"

# ── .github/workflows symlink ─────────────────────────────────────────────
step "Setting up GitHub Actions"
if [ ! -d ".github/workflows" ]; then
  mkdir -p .github/workflows
fi
# Copy generated workflows into .github/workflows/
if [ -d "infrastructure/github_actions" ]; then
  cp infrastructure/github_actions/*.yml .github/workflows/ 2>/dev/null && \
    ok "GitHub Actions workflows copied to .github/workflows/" || \
    warn "No workflows generated yet — run: python3 ngr.py infra generate --type github-actions"
else
  warn "infrastructure/github_actions not found — run: python3 ngr.py infra generate --all"
fi

# ── Connection test ───────────────────────────────────────────────────────
step "Testing connections"

if [ -f ".env" ]; then
  set -a; source .env 2>/dev/null; set +a
fi

python3 scripts/test_connections.py 2>/dev/null || warn "Connection test not run (run manually: python3 scripts/test_connections.py)"

# ── Final summary ─────────────────────────────────────────────────────────
echo ""
echo "  ╔══════════════════════════════════════════════╗"
echo "  ║   Setup complete. Next steps:                ║"
echo "  ╠══════════════════════════════════════════════╣"
echo "  ║  1. Fill in .env with your credentials       ║"
echo "  ║  2. python3 scripts/test_connections.py      ║"
echo "  ║  3. python3 ngr.py status                    ║"
echo "  ║  4. python3 ngr.py infra generate --all      ║"
echo "  ║  5. See CONNECTIONS.md for full setup guide  ║"
echo "  ╚══════════════════════════════════════════════╝"
echo ""
