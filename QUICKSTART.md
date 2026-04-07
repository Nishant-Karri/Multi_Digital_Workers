# Multi_Digital_Workers — Org Quickstart

Ten steps to go from zero to a fully operational data orchestration platform.

---

## Prerequisites

| Requirement | Minimum Version | Check |
|-------------|----------------|-------|
| Python | 3.11+ | `python3 --version` |
| Git | 2.40+ | `git --version` |
| AWS CLI | 2.x | `aws --version` |
| Terraform | 1.7+ | `terraform --version` |
| dbt Core | 1.7+ | `dbt --version` (optional) |

---

## Step 1 — Clone and run setup

```bash
git clone https://github.com/Nishant-Karri/Multi_Digital_Workers.git
cd Multi_Digital_Workers
bash scripts/setup.sh
```

Setup will:
- Check Python 3.11+
- Create `.venv` and install core dependencies
- Copy `vault/env.template` → `.env`
- Initialize the local vault
- Create all runtime directories

---

## Step 2 — Fill in `.env`

```bash
cp vault/env.template .env   # already done by setup.sh
nano .env                    # or your preferred editor
```

Required fields (everything else is optional):

```env
# Snowflake (required for pipeline runs)
SNOWFLAKE_ACCOUNT=yourorg-youraccountid
SNOWFLAKE_USER=your_user
SNOWFLAKE_PASSWORD=your_password
SNOWFLAKE_ROLE=SYSADMIN
SNOWFLAKE_WAREHOUSE=COMPUTE_WH
SNOWFLAKE_DATABASE=NWT_DB
SNOWFLAKE_SCHEMA=PUBLIC

# AWS (required for Glue + S3)
AWS_DEFAULT_REGION=us-east-1
# Credentials come from AWS CLI profile or instance role — no keys in .env

# JIRA (required for ticket sync)
JIRA_URL=https://yourcompany.atlassian.net
JIRA_USER=your.email@company.com
JIRA_TOKEN=your_jira_api_token

# Alerting (at least one required)
TEAMS_WEBHOOK=https://yourcompany.webhook.office.com/...
SLACK_WEBHOOK=https://hooks.slack.com/services/...
```

---

## Step 3 — Store secrets in vault

```bash
# Interactive: prompts for each value and stores encrypted locally
python3 vault/vault.py set SNOWFLAKE_PASSWORD

# Or batch-set from .env (one-time migration)
python3 vault/vault.py import-env

# Verify
python3 vault/vault.py list
```

---

## Step 4 — Test all connections

```bash
python3 scripts/test_connections.py
```

Expected output:
```
── Snowflake
  ✓  Snowflake  (v8.11.0  340ms)
── AWS
  ✓  AWS STS  (account=123456789012)
  ✓  AWS S3  (3 bucket(s) visible)
── JIRA
  ✓  JIRA Cloud  (user=Nishant Karri)
── Alerting
  ✓  Microsoft Teams  (HTTP 200)
```

---

## Step 5 — Configure your projects + JIRA mapping

Edit `config/projects.json` and add your JIRA project keys to each project's `jira_projects` array:

```json
{
  "id": "nwt",
  "jira_projects": ["NWT", "DE", "DATA"],
  ...
}
```

---

## Step 6 — Generate infrastructure

```bash
# Generate all GitHub Actions workflows + Terraform modules
python3 mdw.py infra generate --all

# Review the generated Terraform plan before applying
python3 mdw.py infra plan --env dev

# Apply dev environment (requires confirmation)
python3 mdw.py infra apply --env dev
```

> **Terraform state bucket** — create this once before first `plan`:
> ```bash
> aws s3 mb s3://your-tfstate-bucket --region us-east-1
> aws s3api put-bucket-versioning --bucket your-tfstate-bucket \
>   --versioning-configuration Status=Enabled
> ```
> Then update `backend.hcl` files in `infrastructure/terraform/envs/*/`.

---

## Step 7 — Set GitHub Actions secrets

In your repo: **Settings → Secrets and variables → Actions**

| Secret | Value |
|--------|-------|
| `SNOWFLAKE_ACCOUNT` | Your Snowflake account |
| `SNOWFLAKE_USER` | Service account user |
| `SNOWFLAKE_PASSWORD` | Password |
| `SNOWFLAKE_ROLE` | e.g. `SYSADMIN` |
| `SNOWFLAKE_WAREHOUSE` | e.g. `COMPUTE_WH` |
| `SNOWFLAKE_DATABASE` | e.g. `NWT_DB` |
| `SNOWFLAKE_SCHEMA` | e.g. `PUBLIC` |
| `AWS_DEPLOY_ROLE_DEV` | IAM role ARN (OIDC) |
| `AWS_DEPLOY_ROLE_PROD` | IAM role ARN (OIDC) |
| `TEAMS_WEBHOOK` | Teams webhook URL |
| `SLACK_WEBHOOK` | Slack webhook URL |

---

## Step 8 — Sync JIRA tickets

```bash
# Fetch all open tickets across configured projects and create tasks
python3 mdw.py jira sync

# Check what was created
python3 mdw.py tasks list --status ready

# Execute a specific ticket
python3 mdw.py jira execute JIRA-123
```

---

## Step 9 — Run your first QA cycle

```bash
# Generate test plan + test cases + sample data
python3 mdw.py qa generate --pipeline nwt_batch_load

# Run all test cases (connects to Snowflake)
python3 mdw.py qa run --pipeline nwt_batch_load

# Generate lineage document
python3 mdw.py qa lineage --pipeline nwt_batch_load

# Publish all artifacts with git tag
python3 mdw.py qa publish --run-id QA-$(date +%Y%m%d)
```

---

## Step 10 — Monitor and investigate

```bash
# Check overall status
python3 mdw.py status

# Run observability check
python3 observability/observer.py run

# Monitor all pipelines (auto-opens incidents on failures)
python3 integrations/reliability.py monitor

# Investigate a specific pipeline
python3 mdw.py investigate run --pipeline nwt_batch_load

# Review and approve fixes
python3 mdw.py investigate list
python3 mdw.py investigate approve INV-XXXXXX

# Apply approved fixes to Snowflake + push to git
python3 mdw.py investigate apply INV-XXXXXX --push
```

---

## Agent Reference

| Agent | Trigger | What it does |
|-------|---------|--------------|
| `data_engineer` | ETL, Glue, S3, Informatica, Talend tasks | Builds and maintains ingestion pipelines |
| `analytics_engineer` | dbt, Snowflake, BI layer tasks | Models, tests, and documents the warehouse |
| `streaming_engineer` | Kafka, Kinesis, CDC tasks | Real-time pipelines and event processing |
| `data_scientist` | ML, feature store, model tasks | Training, evaluation, deployment |
| `governance` | Lineage, PII, catalog, access tasks | Data governance and compliance |
| `reliability` | Incidents, SLOs, alerting | Monitors pipelines, manages incidents |
| `investigator` | Failures, drift, freshness issues | Diagnoses root cause, proposes SQL fixes |
| `qa` | Test generation and execution | Full QA cycle with git versioning |
| `cicd` | GitHub Actions, Terraform | CI/CD pipelines and cloud infrastructure |
| `dataops` | Airflow, cost, platform tasks | Platform reliability and optimization |
| `data_quality` | Great Expectations, SLA | Data quality suites and monitoring |
| `governance` | Collibra, DataHub, PII | Catalog, lineage, access control |

---

## Daily Operations

```bash
# Morning check — run every day
python3 mdw.py status
python3 integrations/reliability.py monitor
python3 mdw.py jira sync

# After every pipeline run
python3 mdw.py qa run --pipeline <name>

# Weekly (Monday)
python3 mdw.py qa full --pipeline nwt_batch_load
python3 mdw.py qa full --pipeline dbt_star_schema
```

---

## Troubleshooting

| Problem | Command |
|---------|---------|
| Connection fails | `python3 scripts/test_connections.py` |
| Vault missing key | `python3 vault/vault.py list` |
| Task stuck | `python3 mdw.py tasks list --status active` |
| Investigation pending | `python3 mdw.py investigate list` |
| Alert not sending | Check `.env` webhook URLs |
| Terraform state error | Verify `backend.hcl` bucket exists |

---

## Support

- Full connector setup: `CONNECTIONS.md`
- Domain reference: `domains/registry.py`
- Agent playbooks: `agents/<agent>/CLAUDE.md`
- Incident war room: `mayor/DOLT-WAR-ROOM.md`
