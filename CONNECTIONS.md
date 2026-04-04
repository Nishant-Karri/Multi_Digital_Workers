# Connections Guide — Nishant_gastown_replica

How to securely connect to every tech stack. No credentials are stored in this repo.

---

## Vault Setup (Do This First)

The vault manages all credentials. Choose one backend:

| Backend | Best For |
|---------|----------|
| **AWS Secrets Manager** | Production, EC2, CI/CD (recommended) |
| **Environment variables** | Local dev, Docker, quick setup |
| **Local encrypted file** | Offline / no cloud access |

### Option A — AWS Secrets Manager (Recommended)

Store each service's credentials as a JSON secret in AWS:

```bash
# Snowflake
aws secretsmanager create-secret \
  --name ngr/snowflake \
  --secret-string '{"account":"xy12345.us-east-1","user":"myuser","password":"mypass","warehouse":"COMPUTE_WH","database":"MYDB","schema":"PUBLIC","role":"SYSADMIN"}'

# KQL
aws secretsmanager create-secret \
  --name ngr/kql \
  --secret-string '{"cluster":"https://mycluster.kusto.windows.net","database":"mydb","tenant_id":"...","client_id":"...","client_secret":"..."}'

# Informatica
aws secretsmanager create-secret \
  --name ngr/informatica \
  --secret-string '{"base_url":"https://dm-us.informaticacloud.com","username":"...","password":"...","org_id":"..."}'

# Talend
aws secretsmanager create-secret \
  --name ngr/talend \
  --secret-string '{"tmc_url":"https://api.us.cloud.talend.com","api_key":"...","workspace_id":"..."}'

# Anthropic
aws secretsmanager create-secret \
  --name ngr/anthropic \
  --secret-string '{"api_key":"sk-ant-..."}'
```

No code changes needed — the vault picks these up automatically.

---

### Option B — Environment Variables

Copy the template and fill in your values:

```bash
cp vault/env.template .env
# Edit .env with your credentials
source .env          # Mac/Linux
```

**Windows PowerShell:**
```powershell
Get-Content .env | Where-Object { $_ -match "=" -and $_ -notmatch "^#" } |
  ForEach-Object { $k,$v = $_ -split "=",2; [System.Environment]::SetEnvironmentVariable($k,$v,"Process") }
```

> `.env` is gitignored — it will never be committed.

---

### Option C — Local Encrypted File

```bash
pip install cryptography
python3 vault/vault.py init

# Add credentials one service at a time
python3 vault/vault.py set snowflake '{"account":"xy12345","user":"me","password":"secret","warehouse":"WH","database":"DB","schema":"PUBLIC","role":"SYSADMIN"}'
python3 vault/vault.py set kql '{"cluster":"https://...","database":"mydb","tenant_id":"...","client_id":"...","client_secret":"..."}'

# Check what's configured
python3 vault/vault.py list
```

The encrypted file lives at `.vault/secrets.enc` — gitignored.

---

## Verify All Connections

```bash
python3 vault/vault.py list
```

Expected output:
```
SERVICE         AVAILABLE IN
---------------------------------------------
  aws           ✓  env
  snowflake     ✓  aws_secrets
  kql           ✓  aws_secrets
  informatica   ✓  local
  talend        ✗  not configured
  dbt           ✓  env
  anthropic     ✓  env
```

---

## AWS

### IAM Role (EC2 — No Keys Needed)

Attach an IAM role to your EC2 instance with the permissions it needs.
boto3 picks it up automatically — no credentials required in code.

```python
from vault.vault import Connectors
c = Connectors()
s3     = c.aws_session("s3")
glue   = c.aws_session("glue")
athena = c.aws_session("athena")
```

### Access Keys (Local Dev Only)

Set in `.env`:
```
AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=...
AWS_DEFAULT_REGION=us-east-1
```

### Key AWS Services Used

| Service | Purpose |
|---------|---------|
| S3 | Landing zone / Curated (Iceberg) |
| Glue | ETL jobs (landing → curated) |
| SSM | EC2 remote management |
| Secrets Manager | Credential storage |
| IAM | Role-based access (preferred over keys) |

**IAM Policy minimum for this project:**
```json
{
  "Effect": "Allow",
  "Action": [
    "s3:GetObject", "s3:PutObject", "s3:ListBucket",
    "glue:StartJobRun", "glue:GetJobRun",
    "secretsmanager:GetSecretValue",
    "ssm:SendCommand", "ssm:StartSession"
  ],
  "Resource": "*"
}
```

---

## Snowflake

### Connect in Python

```python
from vault.vault import Connectors
conn = Connectors().snowflake()
cursor = conn.cursor()
cursor.execute("SELECT CURRENT_USER()")
print(cursor.fetchone())
conn.close()
```

### Connect with pandas

```python
from vault.vault import Vault
import snowflake.connector
from snowflake.connector.pandas_tools import pd_writer
import pandas as pd

c    = Vault().get("snowflake")
conn = snowflake.connector.connect(**c)
df   = pd.read_sql("SELECT * FROM MY_TABLE LIMIT 10", conn)
```

### Credentials needed

| Field | Example |
|-------|---------|
| account | `xy12345.us-east-1` |
| user | `NISHANT` |
| password | (use vault) |
| warehouse | `COMPUTE_WH` |
| database | `NISHANT_DS_DB` |
| schema | `NISHANT_WORKFLOW_TEST` |
| role | `SYSADMIN` |

### Key Pair Auth (More Secure — No Password)

```bash
# Generate key pair
openssl genrsa 2048 | openssl pkcs8 -topk8 -nocrypt -out rsa_key.p8
openssl rsa -in rsa_key.p8 -pubout -out rsa_key.pub

# Register public key in Snowflake
ALTER USER NISHANT SET RSA_PUBLIC_KEY='<contents of rsa_key.pub>';
```

Store `rsa_key.p8` path in vault — no password needed.

---

## SQL (Generic)

### Snowflake via SQLAlchemy

```python
from vault.vault import Vault
from sqlalchemy import create_engine

c = Vault().get("snowflake")
url = (
    f"snowflake://{c['user']}:{c['password']}@{c['account']}"
    f"/{c['database']}/{c['schema']}"
    f"?warehouse={c['warehouse']}&role={c['role']}"
)
engine = create_engine(url)
```

### Run SQL from a file

```python
with engine.connect() as conn:
    sql = open("queries/my_query.sql").read()
    result = conn.execute(sql)
```

---

## KQL (Azure Data Explorer)

### Connect in Python

```python
from vault.vault import Connectors
client = Connectors().kql_client()

from azure.kusto.data import KustoClient
from azure.kusto.data.helpers import dataframe_from_result_table

response = client.execute("MyDatabase", "MyTable | limit 10")
df = dataframe_from_result_table(response.primary_results[0])
print(df)
```

### Credentials needed

| Field | Where to find |
|-------|--------------|
| cluster | Azure Portal → Data Explorer cluster → URI |
| database | Database name inside the cluster |
| tenant_id | Azure AD → Properties → Tenant ID |
| client_id | App Registration → Application (client) ID |
| client_secret | App Registration → Certificates & secrets |

### App Registration Setup (Azure Portal)

1. Azure AD → App registrations → New registration → `ngr-kql-app`
2. Certificates & secrets → New client secret → copy value
3. Go to your ADX cluster → Databases → Permissions → Add → Viewer/Admin → select `ngr-kql-app`

### Install dependency

```bash
pip install azure-kusto-data
```

---

## Informatica (IICS)

### Authenticate and run a job

```python
from vault.vault import Connectors

session = Connectors().informatica_session()
base    = session._ngr_base_url

# List all jobs
jobs = session.get(f"{base}/api/v2/job").json()

# Start a mapping task
session.post(f"{base}/api/v2/job/start", json={
    "@type": "job",
    "taskId": "YOUR_TASK_ID",
    "taskType": "MTT"
})
```

### Get job status

```python
resp = session.get(f"{base}/api/v2/job?taskId=YOUR_TASK_ID")
print(resp.json().get("status"))
```

### Credentials needed

| Field | Where to find |
|-------|--------------|
| base_url | Informatica Cloud console → Settings → base URL |
| username | Your IICS login email |
| password | (use vault) |
| org_id | Settings → Organization ID |

---

## Talend Cloud (TMC)

### Run a job via API

```python
from vault.vault import Vault
import requests

c    = Vault().get("talend")
hdrs = {"Authorization": f"Bearer {c['api_key']}", "Content-Type": "application/json"}

# List executable tasks
tasks = requests.get(f"{c['tmc_url']}/tmc/v2.5/executables/tasks", headers=hdrs).json()

# Run a task
run = requests.post(
    f"{c['tmc_url']}/tmc/v2.5/executables/tasks/YOUR_TASK_ID/executions",
    headers=hdrs
).json()
print(run.get("executionId"))
```

### Check execution status

```python
exec_id = run["executionId"]
status  = requests.get(
    f"{c['tmc_url']}/tmc/v2.5/executables/tasks/YOUR_TASK_ID/executions/{exec_id}",
    headers=hdrs
).json()
print(status.get("status"))  # RUNNING / COMPLETED / FAILED
```

### Credentials needed

| Field | Where to find |
|-------|--------------|
| tmc_url | `https://api.us.cloud.talend.com` or EU equivalent |
| api_key | Talend Cloud → Profile → Personal Access Token |
| workspace_id | Talend Cloud → Management → Workspaces |

---

## dbt

### Run dbt commands

```python
from vault.vault import Connectors
import subprocess, os

env = {**os.environ, **Connectors().dbt_env()}

subprocess.run(["dbt", "run", "--target", "prod"], env=env, check=True)
subprocess.run(["dbt", "test"], env=env, check=True)
```

### profiles.yml (no hardcoded creds)

Store your `profiles.yml` in a directory outside the repo, then point to it via `NGR_DBT_PROFILES_DIR`:

```yaml
# ~/.dbt/profiles.yml  (or wherever NGR_DBT_PROFILES_DIR points)
nishant_workflow_test:
  target: "{{ env_var('DBT_TARGET', 'dev') }}"
  outputs:
    prod:
      type: snowflake
      account: "{{ env_var('DBT_SNOWFLAKE_ACCOUNT') }}"
      user: "{{ env_var('DBT_SNOWFLAKE_USER') }}"
      password: "{{ env_var('DBT_SNOWFLAKE_PASSWORD') }}"
      warehouse: "{{ env_var('DBT_SNOWFLAKE_WAREHOUSE') }}"
      database: "{{ env_var('DBT_SNOWFLAKE_DATABASE') }}"
      schema: "{{ env_var('DBT_SNOWFLAKE_SCHEMA') }}"
      threads: 4
```

All values come from environment — zero credentials in the file.

---

## Quick Reference

```python
from vault.vault import Vault, Connectors

v = Vault()
c = Connectors(v)

# AWS
s3      = c.aws_session("s3")

# Snowflake
sf_conn = c.snowflake()

# KQL
kql     = c.kql_client()

# Informatica
iics    = c.informatica_session()

# dbt
env     = c.dbt_env()

# Raw creds (avoid unless necessary)
sf_raw  = v.get("snowflake")
```

---

## JIRA

**Get API token:** https://id.atlassian.com/manage-profile/security/api-tokens

```bash
# Test connection
python3 integrations/jira.py test

# Set via env
export NGR_JIRA_BASE_URL="https://yourcompany.atlassian.net"
export NGR_JIRA_USER="your-email@company.com"
export NGR_JIRA_TOKEN="your-api-token"

# Or via vault
python3 vault/vault.py set jira '{
  "base_url": "https://yourcompany.atlassian.net",
  "user": "your-email@company.com",
  "token": "your-api-token",
  "api_version": "3"
}'
```

**JIRA Server / Data Center:**
```bash
python3 vault/vault.py set jira '{
  "base_url": "https://jira.yourcompany.com",
  "user": "your-username",
  "token": "your-password",
  "api_version": "2"
}'
```

**Usage:**
```bash
python3 ngr.py jira test                          # verify connection
python3 ngr.py jira projects                      # list accessible projects
python3 ngr.py jira sync --project DATA           # sync all open tickets
python3 ngr.py jira sync --project DATA --status "To Do" --max 20
python3 ngr.py jira fetch DATA-123                # view single ticket
python3 ngr.py jira execute DATA-123              # fetch + create task + instruction.md
python3 ngr.py jira update DATA-123 --status "In Progress" --comment "Starting work"
python3 ngr.py jira list                          # list synced tickets
```

---

## Microsoft Teams Alerts

**Setup:** Teams channel → `···` → Connectors → Incoming Webhook → Configure → Copy URL

```bash
export NGR_TEAMS_WEBHOOK="https://yourcompany.webhook.office.com/webhookb2/..."

# Test
python3 integrations/alerts.py --channel teams --severity HIGH
```

---

## Slack Alerts

**Option A — Incoming Webhook (simple):**
1. Go to api.slack.com/apps → Create App → Incoming Webhooks → Add New Webhook
2. Copy the webhook URL

```bash
export NGR_SLACK_WEBHOOK="https://hooks.slack.com/services/T.../B.../...."

# Test
python3 integrations/alerts.py --channel slack --severity HIGH
```

**Option B — Bot Token (post to any channel):**
1. api.slack.com/apps → Create App → OAuth & Permissions → Bot Token Scopes: `chat:write`
2. Install app to workspace → copy Bot Token (xoxb-...)

```bash
export NGR_SLACK_BOT_TOKEN="xoxb-..."
export NGR_SLACK_ALERT_CHANNEL="#data-alerts"
```

---

## Email / Outlook Alerts

**Option A — SMTP (Office 365):**
```bash
export NGR_SMTP_HOST="smtp.office365.com"
export NGR_SMTP_PORT="587"
export NGR_SMTP_USER="alerts@yourcompany.com"
export NGR_SMTP_PASSWORD="your-app-password"   # NOT your login password
export NGR_SMTP_FROM="alerts@yourcompany.com"
export NGR_ALERT_EMAILS="oncall@yourcompany.com,dataplatform@yourcompany.com"

# Test
python3 integrations/alerts.py --channel email --severity MEDIUM
```

> **Office 365 app password:** Microsoft 365 Admin → Users → your user → Mail → Email apps → Enable SMTP AUTH

**Option B — Microsoft Graph API (if SMTP is disabled on your tenant):**

1. Azure Portal → App Registrations → New Registration
2. API Permissions → Add: `Mail.Send` (Application, not Delegated)
3. Grant admin consent
4. Certificates & Secrets → New client secret → copy value

```bash
export NGR_GRAPH_TENANT_ID="your-tenant-id"
export NGR_GRAPH_CLIENT_ID="your-app-client-id"
export NGR_GRAPH_CLIENT_SECRET="your-client-secret"
export NGR_GRAPH_SENDER_EMAIL="alerts@yourcompany.com"
export NGR_ALERT_EMAILS="oncall@yourcompany.com"
```

**Via vault:**
```bash
python3 vault/vault.py set graph '{
  "tenant_id": "...", "client_id": "...",
  "client_secret": "...", "sender_email": "alerts@yourcompany.com"
}'
```

---

## Testing All Alert Channels

```bash
# Test all configured channels at once
python3 integrations/alerts.py --severity HIGH --title "NGR Test Alert"

# Or via ngr CLI
python3 ngr.py alert \
  --title "Test: Pipeline health check" \
  --body "All systems nominal. This is a test." \
  --severity MEDIUM
```

---

## Data Reliability Agent

```bash
# Full pipeline health check
python3 integrations/reliability.py monitor

# SLO compliance report
python3 integrations/reliability.py slo --days 30

# Incident management
python3 integrations/reliability.py incident open --title "..." --severity P2-HIGH --pipeline nwt_batch_load
python3 integrations/reliability.py incident list
python3 integrations/reliability.py incident update INC-ABC123 --status RESOLVED --notes "Fixed."
python3 integrations/reliability.py incident rca INC-ABC123 --cause "API throttling" --category dependency_failure
```

---

## Security Rules

1. **Never put credentials in code or config files** — use the vault
2. **Never commit `.env`, `.vault/`, or any file with credentials** — they are gitignored
3. **Use IAM roles on EC2** instead of access keys wherever possible
4. **Rotate credentials** if they are ever exposed (e.g. in chat, logs, PRs)
5. **AWS Secrets Manager** is the production-grade solution — use it for any shared environment
6. **Key pair auth** (instead of passwords) is available for Snowflake — prefer it
