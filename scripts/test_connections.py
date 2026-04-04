#!/usr/bin/env python3
"""
scripts/test_connections.py — Test all configured connections.
Run: python3 scripts/test_connections.py
"""
import os
import sys
import json
import time

GREEN = "\033[0;32m"
RED   = "\033[0;31m"
YELLOW= "\033[1;33m"
NC    = "\033[0m"

def ok(name, detail=""):
    tag = f"  ({detail})" if detail else ""
    print(f"  {GREEN}✓{NC}  {name}{tag}")

def fail(name, err):
    print(f"  {RED}✗{NC}  {name}  ({err})")

def skip(name, reason):
    print(f"  {YELLOW}–{NC}  {name}  (skipped: {reason})")

def section(title):
    print(f"\n  {YELLOW}── {title}{NC}")

results = {"passed": 0, "failed": 0, "skipped": 0}

def _ok(n, d=""):   results["passed"]  += 1; ok(n, d)
def _fail(n, e):    results["failed"]  += 1; fail(n, e)
def _skip(n, r):    results["skipped"] += 1; skip(n, r)

# ── Snowflake ──────────────────────────────────────────────────────────────
section("Snowflake")
try:
    acct = os.environ.get("SNOWFLAKE_ACCOUNT")
    user = os.environ.get("SNOWFLAKE_USER")
    pwd  = os.environ.get("SNOWFLAKE_PASSWORD")
    if not all([acct, user, pwd]):
        _skip("Snowflake", "SNOWFLAKE_ACCOUNT / USER / PASSWORD not set")
    else:
        import snowflake.connector
        t0 = time.time()
        conn = snowflake.connector.connect(
            account   = acct,
            user      = user,
            password  = pwd,
            warehouse = os.environ.get("SNOWFLAKE_WAREHOUSE", ""),
            database  = os.environ.get("SNOWFLAKE_DATABASE", ""),
            schema    = os.environ.get("SNOWFLAKE_SCHEMA", ""),
            login_timeout = 15,
        )
        row = conn.cursor().execute("SELECT CURRENT_VERSION()").fetchone()
        conn.close()
        _ok("Snowflake", f"v{row[0]}  {int((time.time()-t0)*1000)}ms")
except ImportError:
    _fail("Snowflake", "snowflake-connector-python not installed — pip install snowflake-connector-python")
except Exception as e:
    _fail("Snowflake", str(e)[:80])

# ── AWS ────────────────────────────────────────────────────────────────────
section("AWS")
try:
    import boto3
    sts = boto3.client("sts")
    identity = sts.get_caller_identity()
    _ok("AWS STS", f"account={identity['Account']}  arn={identity['Arn'].split('/')[-1]}")
except ImportError:
    _fail("AWS STS", "boto3 not installed — pip install boto3")
except Exception as e:
    _fail("AWS STS", str(e)[:80])

try:
    region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
    s3 = boto3.client("s3", region_name=region)
    buckets = s3.list_buckets().get("Buckets", [])
    _ok("AWS S3", f"{len(buckets)} bucket(s) visible")
except Exception as e:
    _fail("AWS S3", str(e)[:80])

try:
    glue = boto3.client("glue", region_name=region)
    glue.list_jobs(MaxResults=1)
    _ok("AWS Glue", "list_jobs OK")
except Exception as e:
    _fail("AWS Glue", str(e)[:80])

# ── JIRA ──────────────────────────────────────────────────────────────────
section("JIRA")
try:
    jira_url  = os.environ.get("JIRA_URL")
    jira_user = os.environ.get("JIRA_USER")
    jira_tok  = os.environ.get("JIRA_TOKEN")
    if not all([jira_url, jira_user, jira_tok]):
        _skip("JIRA", "JIRA_URL / JIRA_USER / JIRA_TOKEN not set")
    else:
        import requests
        from requests.auth import HTTPBasicAuth
        r = requests.get(
            f"{jira_url.rstrip('/')}/rest/api/3/myself",
            auth=HTTPBasicAuth(jira_user, jira_tok),
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        _ok("JIRA Cloud", f"user={data.get('displayName','?')}  email={data.get('emailAddress','?')}")
except Exception as e:
    _fail("JIRA", str(e)[:80])

# ── Microsoft Teams ────────────────────────────────────────────────────────
section("Alerting")
try:
    teams_wh = os.environ.get("TEAMS_WEBHOOK")
    if not teams_wh:
        _skip("Microsoft Teams", "TEAMS_WEBHOOK not set")
    else:
        import requests
        payload = {"type": "message", "attachments": [{"contentType": "application/vnd.microsoft.card.adaptive",
            "content": {"type": "AdaptiveCard", "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "version": "1.4", "body": [{"type": "TextBlock", "text": "NGR connection test ✓"}]}}]}
        r = requests.post(teams_wh, json=payload, timeout=10)
        _ok("Microsoft Teams", f"HTTP {r.status_code}")
except Exception as e:
    _fail("Microsoft Teams", str(e)[:80])

try:
    slack_wh = os.environ.get("SLACK_WEBHOOK")
    if not slack_wh:
        _skip("Slack", "SLACK_WEBHOOK not set")
    else:
        import requests
        r = requests.post(slack_wh, json={"text": "NGR connection test ✓"}, timeout=10)
        _ok("Slack webhook", f"HTTP {r.status_code}")
except Exception as e:
    _fail("Slack webhook", str(e)[:80])

try:
    smtp_host = os.environ.get("SMTP_HOST")
    smtp_user = os.environ.get("SMTP_USER")
    smtp_pass = os.environ.get("SMTP_PASSWORD")
    if not smtp_host:
        _skip("SMTP/Outlook", "SMTP_HOST not set")
    else:
        import smtplib
        port = int(os.environ.get("SMTP_PORT", "587"))
        s = smtplib.SMTP(smtp_host, port, timeout=10)
        s.starttls()
        if smtp_user and smtp_pass:
            s.login(smtp_user, smtp_pass)
        s.quit()
        _ok("SMTP/Outlook", f"{smtp_host}:{port}")
except Exception as e:
    _fail("SMTP/Outlook", str(e)[:80])

# ── Azure KQL ─────────────────────────────────────────────────────────────
section("Azure")
try:
    kql_cluster = os.environ.get("KQL_CLUSTER")
    kql_db      = os.environ.get("KQL_DATABASE")
    tenant_id   = os.environ.get("AZURE_TENANT_ID")
    client_id   = os.environ.get("AZURE_CLIENT_ID")
    client_sec  = os.environ.get("AZURE_CLIENT_SECRET")
    if not kql_cluster:
        _skip("Azure KQL/ADX", "KQL_CLUSTER not set")
    else:
        from azure.kusto.data import KustoClient, KustoConnectionStringBuilder
        from azure.identity import ClientSecretCredential
        if all([tenant_id, client_id, client_sec]):
            kcsb = KustoConnectionStringBuilder.with_aad_application_key_authentication(
                kql_cluster, client_id, client_sec, tenant_id)
        else:
            kcsb = KustoConnectionStringBuilder.with_az_cli_authentication(kql_cluster)
        client = KustoClient(kcsb)
        resp = client.execute(kql_db, ".show version")
        _ok("Azure KQL/ADX", f"cluster={kql_cluster.split('.')[0]}")
except ImportError:
    _fail("Azure KQL/ADX", "azure-kusto-data not installed — pip install azure-kusto-data azure-identity")
except Exception as e:
    _fail("Azure KQL/ADX", str(e)[:80])

# ── Vault ──────────────────────────────────────────────────────────────────
section("Vault")
try:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from vault.vault import Vault
    v = Vault()
    v.health_check()
    _ok("Vault", "local backend OK")
except Exception as e:
    _fail("Vault", str(e)[:80])

# ── Observability baselines ────────────────────────────────────────────────
section("Observability")
for fname in ["observability/snapshots/row_counts.json",
              "observability/snapshots/data_drift_baseline.json"]:
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), fname)
    if os.path.exists(path):
        _ok(fname.split("/")[-1])
    else:
        _fail(fname.split("/")[-1], "file missing — run scripts/setup.sh")

# ── Summary ───────────────────────────────────────────────────────────────
print(f"""
  ╔══════════════════════════════════════════╗
  ║  Results: {results['passed']:>2} passed  {results['failed']:>2} failed  {results['skipped']:>2} skipped  ║
  ╚══════════════════════════════════════════╝
""")

if results["failed"] > 0:
    sys.exit(1)
