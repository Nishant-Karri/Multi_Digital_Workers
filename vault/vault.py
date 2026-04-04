#!/usr/bin/env python3
"""
vault.py — Credential Vault for Nishant_gastown_replica

Loads credentials from (in priority order):
  1. AWS Secrets Manager   (production — recommended)
  2. Environment variables (CI/CD, EC2 with IAM role)
  3. Local encrypted file  (.vault/secrets.enc — never committed to git)

Usage:
  from vault.vault import Vault
  v = Vault()
  sf  = v.get("snowflake")
  aws = v.get("aws")

NEVER hardcode credentials. NEVER commit .vault/secrets.enc or .env to git.
"""

import base64
import json
import os
import sys
from pathlib import Path
from typing import Optional

ROOT       = Path(__file__).parent.parent
VAULT_DIR  = ROOT / ".vault"
ENC_FILE   = VAULT_DIR / "secrets.enc"
KEY_FILE   = VAULT_DIR / "vault.key"


# ── Backend: Environment Variables ───────────────────────────────────────────

class EnvBackend:
    """Reads credentials from environment variables (prefixed NGR_)."""

    PREFIX = "NGR_"

    KEYS = {
        "aws": [
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "AWS_SESSION_TOKEN",
            "AWS_DEFAULT_REGION",
        ],
        "snowflake": [
            "NGR_SNOWFLAKE_ACCOUNT",
            "NGR_SNOWFLAKE_USER",
            "NGR_SNOWFLAKE_PASSWORD",
            "NGR_SNOWFLAKE_WAREHOUSE",
            "NGR_SNOWFLAKE_DATABASE",
            "NGR_SNOWFLAKE_SCHEMA",
            "NGR_SNOWFLAKE_ROLE",
        ],
        "kql": [
            "NGR_KQL_CLUSTER",
            "NGR_KQL_DATABASE",
            "NGR_KQL_TENANT_ID",
            "NGR_KQL_CLIENT_ID",
            "NGR_KQL_CLIENT_SECRET",
        ],
        "informatica": [
            "NGR_INFORMATICA_BASE_URL",
            "NGR_INFORMATICA_USERNAME",
            "NGR_INFORMATICA_PASSWORD",
            "NGR_INFORMATICA_ORG_ID",
        ],
        "talend": [
            "NGR_TALEND_TMC_URL",
            "NGR_TALEND_API_KEY",
            "NGR_TALEND_WORKSPACE_ID",
        ],
        "dbt": [
            "NGR_DBT_PROFILES_DIR",
            "NGR_DBT_TARGET",
        ],
        "kafka": [
            "NGR_KAFKA_BOOTSTRAP_SERVERS",
            "NGR_KAFKA_SASL_MECHANISM",
            "NGR_KAFKA_SECURITY_PROTOCOL",
            "NGR_KAFKA_SASL_USERNAME",
            "NGR_KAFKA_SASL_PASSWORD",
            "NGR_KAFKA_GROUP_ID",
        ],
        "databricks": [
            "NGR_DATABRICKS_HOST",
            "NGR_DATABRICKS_HTTP_PATH",
            "NGR_DATABRICKS_TOKEN",
        ],
        "mlflow": [
            "NGR_MLFLOW_TRACKING_URI",
            "NGR_MLFLOW_USERNAME",
            "NGR_MLFLOW_PASSWORD",
        ],
        "airflow": [
            "NGR_AIRFLOW_BASE_URL",
            "NGR_AIRFLOW_USER",
            "NGR_AIRFLOW_PASSWORD",
        ],
        "datahub": [
            "NGR_DATAHUB_SERVER",
            "NGR_DATAHUB_TOKEN",
        ],
        "collibra": [
            "NGR_COLLIBRA_BASE_URL",
            "NGR_COLLIBRA_USER",
            "NGR_COLLIBRA_PASSWORD",
        ],
        "feast": [
            "NGR_FEAST_REPO_PATH",
        ],
        "azure_ml": [
            "NGR_AZURE_ML_SUBSCRIPTION_ID",
            "NGR_AZURE_ML_RESOURCE_GROUP",
            "NGR_AZURE_ML_WORKSPACE_NAME",
            "NGR_AZURE_ML_TENANT_ID",
            "NGR_AZURE_ML_CLIENT_ID",
            "NGR_AZURE_ML_CLIENT_SECRET",
        ],
        "gcp": [
            "GOOGLE_APPLICATION_CREDENTIALS",
            "NGR_GCP_PROJECT",
        ],
        "jira": [
            "NGR_JIRA_BASE_URL",
            "NGR_JIRA_USER",
            "NGR_JIRA_TOKEN",
            "NGR_JIRA_API_VERSION",
            "NGR_JIRA_INCIDENT_PROJECT",
        ],
        "teams": [
            "NGR_TEAMS_WEBHOOK",
        ],
        "slack": [
            "NGR_SLACK_WEBHOOK",
            "NGR_SLACK_BOT_TOKEN",
            "NGR_SLACK_ALERT_CHANNEL",
        ],
        "smtp": [
            "NGR_SMTP_HOST",
            "NGR_SMTP_PORT",
            "NGR_SMTP_USER",
            "NGR_SMTP_PASSWORD",
            "NGR_SMTP_FROM",
            "NGR_ALERT_EMAILS",
        ],
        "graph": [
            "NGR_GRAPH_TENANT_ID",
            "NGR_GRAPH_CLIENT_ID",
            "NGR_GRAPH_CLIENT_SECRET",
            "NGR_GRAPH_SENDER_EMAIL",
        ],
        "anthropic": [
            "ANTHROPIC_API_KEY",
        ],
    }

    def get(self, service: str) -> Optional[dict]:
        keys = self.KEYS.get(service)
        if not keys:
            return None
        result = {}
        for k in keys:
            val = os.environ.get(k)
            if val:
                short = k.replace("NGR_", "").replace(f"{service.upper()}_", "").lower()
                result[short] = val
        return result if result else None

    def available(self, service: str) -> bool:
        keys = self.KEYS.get(service, [])
        return any(os.environ.get(k) for k in keys)


# ── Backend: AWS Secrets Manager ─────────────────────────────────────────────

class AWSSecretsBackend:
    """Fetches credentials from AWS Secrets Manager."""

    SECRET_NAMES = {
        "snowflake":   "ngr/snowflake",
        "kql":         "ngr/kql",
        "informatica": "ngr/informatica",
        "talend":      "ngr/talend",
        "dbt":         "ngr/dbt",
        "anthropic":   "ngr/anthropic",
    }

    def __init__(self):
        self._client = None

    def _client_or_none(self):
        if self._client:
            return self._client
        try:
            import boto3
            self._client = boto3.client("secretsmanager")
            return self._client
        except Exception:
            return None

    def get(self, service: str) -> Optional[dict]:
        name = self.SECRET_NAMES.get(service)
        if not name:
            return None
        client = self._client_or_none()
        if not client:
            return None
        try:
            resp = client.get_secret_value(SecretId=name)
            return json.loads(resp["SecretString"])
        except Exception:
            return None

    def available(self, service: str) -> bool:
        return self.get(service) is not None


# ── Backend: Local Encrypted File ─────────────────────────────────────────────

class LocalEncryptedBackend:
    """
    Reads from .vault/secrets.enc — AES encrypted via Fernet.
    Key stored in .vault/vault.key (chmod 600, never committed).

    Setup:
      python3 vault/vault.py init
      python3 vault/vault.py set snowflake '{"account":"...","user":"..."}'
    """

    def __init__(self):
        self._data = None

    def _load(self):
        if self._data is not None:
            return self._data
        if not ENC_FILE.exists() or not KEY_FILE.exists():
            self._data = {}
            return self._data
        try:
            from cryptography.fernet import Fernet
            key  = KEY_FILE.read_bytes()
            f    = Fernet(key)
            raw  = f.decrypt(ENC_FILE.read_bytes())
            self._data = json.loads(raw)
        except ImportError:
            print("⚠  cryptography not installed: pip install cryptography", file=sys.stderr)
            self._data = {}
        except Exception as e:
            print(f"⚠  Could not decrypt vault: {e}", file=sys.stderr)
            self._data = {}
        return self._data

    def get(self, service: str) -> Optional[dict]:
        data = self._load()
        return data.get(service)

    def available(self, service: str) -> bool:
        return self.get(service) is not None

    @staticmethod
    def init():
        """Generate a new vault key and empty secrets file."""
        try:
            from cryptography.fernet import Fernet
        except ImportError:
            print("Run: pip install cryptography")
            sys.exit(1)
        VAULT_DIR.mkdir(exist_ok=True)
        if KEY_FILE.exists():
            print("Vault already initialized. Delete .vault/vault.key to reset.")
            return
        key = Fernet.generate_key()
        KEY_FILE.write_bytes(key)
        KEY_FILE.chmod(0o600)
        # Write empty secrets
        f   = Fernet(key)
        enc = f.encrypt(json.dumps({}).encode())
        ENC_FILE.write_bytes(enc)
        ENC_FILE.chmod(0o600)
        print("✓ Vault initialized at .vault/")
        print("  Key:     .vault/vault.key  (chmod 600 — never commit)")
        print("  Secrets: .vault/secrets.enc (chmod 600 — never commit)")

    @staticmethod
    def set_secret(service: str, value: dict):
        """Write/update a service's credentials in the vault."""
        try:
            from cryptography.fernet import Fernet
        except ImportError:
            print("Run: pip install cryptography")
            sys.exit(1)
        if not KEY_FILE.exists():
            print("Vault not initialized. Run: python3 vault/vault.py init")
            sys.exit(1)
        key = KEY_FILE.read_bytes()
        f   = Fernet(key)
        # Load existing
        try:
            data = json.loads(f.decrypt(ENC_FILE.read_bytes()))
        except Exception:
            data = {}
        data[service] = value
        ENC_FILE.write_bytes(f.encrypt(json.dumps(data).encode()))
        print(f"✓ Credentials saved for: {service}")


# ── Main Vault ────────────────────────────────────────────────────────────────

class Vault:
    """
    Credential vault with automatic backend fallback.

    Priority: AWS Secrets Manager → Environment Variables → Local Encrypted File
    """

    def __init__(self, prefer: str = "auto"):
        self._backends = {
            "aws_secrets": AWSSecretsBackend(),
            "env":         EnvBackend(),
            "local":       LocalEncryptedBackend(),
        }
        self._prefer = prefer

    def get(self, service: str) -> dict:
        """
        Returns credentials for a service.
        Raises RuntimeError if not found in any backend.
        """
        order = (
            ["aws_secrets", "env", "local"] if self._prefer == "auto"
            else [self._prefer]
        )
        for backend_name in order:
            backend = self._backends[backend_name]
            creds = backend.get(service)
            if creds:
                return creds

        raise RuntimeError(
            f"No credentials found for '{service}'.\n"
            f"Set them via one of:\n"
            f"  1. AWS Secrets Manager secret: ngr/{service}\n"
            f"  2. Environment variables (see vault/env.template)\n"
            f"  3. Local vault: python3 vault/vault.py set {service} '{{...}}'"
        )

    def get_or_none(self, service: str) -> Optional[dict]:
        try:
            return self.get(service)
        except RuntimeError:
            return None

    def list_available(self) -> dict:
        """Show which services have credentials configured in any backend."""
        services = ["aws", "snowflake", "kql", "informatica", "talend", "dbt", "anthropic"]
        result = {}
        for svc in services:
            found_in = []
            for name, backend in self._backends.items():
                if backend.available(svc):
                    found_in.append(name)
            result[svc] = found_in if found_in else None
        return result


# ── Connectors ────────────────────────────────────────────────────────────────

class Connectors:
    """Ready-to-use connection objects for each tech stack."""

    def __init__(self, vault: Vault = None):
        self.vault = vault or Vault()

    def snowflake(self):
        """Returns a snowflake.connector.Connection."""
        import snowflake.connector
        c = self.vault.get("snowflake")
        return snowflake.connector.connect(
            account=c.get("account"),
            user=c.get("user"),
            password=c.get("password"),
            warehouse=c.get("warehouse"),
            database=c.get("database"),
            schema=c.get("schema"),
            role=c.get("role"),
        )

    def aws_session(self, service: str = None):
        """Returns a boto3 Session (uses IAM role if on EC2, else env vars)."""
        import boto3
        c = self.vault.get_or_none("aws")
        if c and c.get("access_key_id"):
            session = boto3.Session(
                aws_access_key_id=c.get("access_key_id"),
                aws_secret_access_key=c.get("secret_access_key"),
                aws_session_token=c.get("session_token"),
                region_name=c.get("default_region", "us-east-1"),
            )
        else:
            session = boto3.Session()  # Uses IAM role / instance profile
        return session.client(service) if service else session

    def kql_client(self):
        """Returns a Kusto client for Azure Data Explorer (KQL)."""
        from azure.kusto.data import KustoClient, KustoConnectionStringBuilder
        c = self.vault.get("kql")
        kcsb = KustoConnectionStringBuilder.with_aad_application_key_authentication(
            connection_string=c.get("cluster"),
            aad_app_id=c.get("client_id"),
            app_key=c.get("client_secret"),
            authority_id=c.get("tenant_id"),
        )
        return KustoClient(kcsb)

    def informatica_session(self):
        """Returns requests.Session with Informatica IICS auth headers."""
        import requests
        c = self.vault.get("informatica")
        session = requests.Session()
        resp = session.post(
            f"{c.get('base_url')}/ma/api/v2/user/login",
            json={"@type": "login", "username": c.get("username"), "password": c.get("password")},
        )
        resp.raise_for_status()
        token = resp.json().get("userInfo", {}).get("sessionId")
        session.headers.update({
            "icSessionId": token,
            "Content-Type": "application/json",
        })
        session._ngr_base_url = c.get("base_url")
        return session

    def dbt_env(self) -> dict:
        """Returns env vars to pass when running dbt CLI commands."""
        c = self.vault.get("dbt")
        sf = self.vault.get_or_none("snowflake") or {}
        return {
            "DBT_PROFILES_DIR":        c.get("profiles_dir", str(ROOT / "dbt")),
            "DBT_TARGET":              c.get("target", "prod"),
            "DBT_SNOWFLAKE_ACCOUNT":   sf.get("account", ""),
            "DBT_SNOWFLAKE_USER":      sf.get("user", ""),
            "DBT_SNOWFLAKE_PASSWORD":  sf.get("password", ""),
            "DBT_SNOWFLAKE_WAREHOUSE": sf.get("warehouse", ""),
            "DBT_SNOWFLAKE_DATABASE":  sf.get("database", ""),
            "DBT_SNOWFLAKE_SCHEMA":    sf.get("schema", ""),
        }


# ── CLI ───────────────────────────────────────────────────────────────────────

def cli():
    import argparse
    parser = argparse.ArgumentParser(prog="vault", description="NGR Credential Vault")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("init", help="Initialize local encrypted vault")

    sp = sub.add_parser("set", help="Store credentials for a service")
    sp.add_argument("service", help="e.g. snowflake, kql, informatica")
    sp.add_argument("json_creds", help='JSON string, e.g. \'{"account":"..."}\'')

    sub.add_parser("list", help="Show which services have credentials configured")

    gp = sub.add_parser("get", help="Print credentials for a service (careful!)")
    gp.add_argument("service")

    args = parser.parse_args()

    if args.cmd == "init":
        LocalEncryptedBackend.init()

    elif args.cmd == "set":
        try:
            data = json.loads(args.json_creds)
        except json.JSONDecodeError as e:
            print(f"Invalid JSON: {e}")
            sys.exit(1)
        LocalEncryptedBackend.set_secret(args.service, data)

    elif args.cmd == "list":
        v = Vault()
        status = v.list_available()
        print(f"\n{'SERVICE':15s} {'AVAILABLE IN'}")
        print("-" * 45)
        for svc, backends in status.items():
            if backends:
                print(f"  {svc:13s} ✓  {', '.join(backends)}")
            else:
                print(f"  {svc:13s} ✗  not configured")

    elif args.cmd == "get":
        v = Vault()
        try:
            creds = v.get(args.service)
            # Mask passwords
            safe = {k: ("***" if "password" in k or "secret" in k or "key" in k else v)
                    for k, v in creds.items()}
            print(json.dumps(safe, indent=2))
        except RuntimeError as e:
            print(str(e))
            sys.exit(1)

    else:
        parser.print_help()


if __name__ == "__main__":
    cli()
