#!/usr/bin/env python3
"""
connectors/registry.py — Universal Connector Registry

Maps every platform in the domain registry to:
  - required vault keys
  - connection factory function
  - health-check query/command
  - notes for the agent

Agents call: ConnectorRegistry.connect(platform) → live connection
"""

import os
import sys
import importlib

# Lazy vault import (vault may not be installed in minimal envs)
def _vault():
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    from vault.vault import Vault
    return Vault()


# ── Connector factories ────────────────────────────────────────────────────

def _snowflake(creds: dict):
    import snowflake.connector
    conn = snowflake.connector.connect(
        account   = creds["account"],
        user      = creds["user"],
        password  = creds.get("password"),
        private_key_path = creds.get("private_key_path"),
        role      = creds.get("role"),
        warehouse = creds.get("warehouse"),
        database  = creds.get("database"),
        schema    = creds.get("schema"),
    )
    return conn


def _redshift(creds: dict):
    import psycopg2
    return psycopg2.connect(
        host     = creds["host"],
        port     = int(creds.get("port", 5439)),
        dbname   = creds["database"],
        user     = creds["user"],
        password = creds["password"],
        sslmode  = "require",
    )


def _bigquery(creds: dict):
    from google.cloud import bigquery
    from google.oauth2 import service_account
    sa_info = creds.get("service_account_json")
    if sa_info:
        import json
        sa_dict = json.loads(sa_info) if isinstance(sa_info, str) else sa_info
        credentials = service_account.Credentials.from_service_account_info(sa_dict)
        return bigquery.Client(project=creds["project"], credentials=credentials)
    return bigquery.Client(project=creds["project"])  # uses ADC


def _databricks(creds: dict):
    from databricks import sql
    return sql.connect(
        server_hostname = creds["host"],
        http_path       = creds["http_path"],
        access_token    = creds["token"],
    )


def _postgres(creds: dict):
    import psycopg2
    return psycopg2.connect(
        host     = creds["host"],
        port     = int(creds.get("port", 5432)),
        dbname   = creds["database"],
        user     = creds["user"],
        password = creds["password"],
    )


def _mysql(creds: dict):
    import mysql.connector
    return mysql.connector.connect(
        host     = creds["host"],
        port     = int(creds.get("port", 3306)),
        database = creds["database"],
        user     = creds["user"],
        password = creds["password"],
    )


def _sqlserver(creds: dict):
    import pyodbc
    dsn = (
        f"DRIVER={{ODBC Driver 18 for SQL Server}};"
        f"SERVER={creds['host']},{creds.get('port', 1433)};"
        f"DATABASE={creds['database']};"
        f"UID={creds['user']};"
        f"PWD={creds['password']}"
    )
    return pyodbc.connect(dsn)


def _kafka(creds: dict):
    from confluent_kafka import Consumer
    conf = {
        "bootstrap.servers": creds["bootstrap_servers"],
        "group.id":          creds.get("group_id", "ngr-consumer"),
        "auto.offset.reset": creds.get("auto_offset_reset", "earliest"),
    }
    if creds.get("sasl_mechanism"):
        conf.update({
            "security.protocol":  creds.get("security_protocol", "SASL_SSL"),
            "sasl.mechanism":     creds["sasl_mechanism"],
            "sasl.username":      creds["sasl_username"],
            "sasl.password":      creds["sasl_password"],
        })
    return Consumer(conf)


def _kafka_producer(creds: dict):
    from confluent_kafka import Producer
    conf = {"bootstrap.servers": creds["bootstrap_servers"]}
    if creds.get("sasl_mechanism"):
        conf.update({
            "security.protocol": creds.get("security_protocol", "SASL_SSL"),
            "sasl.mechanism":    creds["sasl_mechanism"],
            "sasl.username":     creds["sasl_username"],
            "sasl.password":     creds["sasl_password"],
        })
    return Producer(conf)


def _kinesis(creds: dict):
    import boto3
    session = boto3.Session(
        aws_access_key_id     = creds.get("aws_access_key_id"),
        aws_secret_access_key = creds.get("aws_secret_access_key"),
        aws_session_token     = creds.get("aws_session_token"),
        region_name           = creds.get("region", "us-east-1"),
    )
    return session.client("kinesis")


def _s3(creds: dict):
    import boto3
    session = boto3.Session(
        aws_access_key_id     = creds.get("aws_access_key_id"),
        aws_secret_access_key = creds.get("aws_secret_access_key"),
        aws_session_token     = creds.get("aws_session_token"),
        region_name           = creds.get("region", "us-east-1"),
    )
    return session.client("s3")


def _glue(creds: dict):
    import boto3
    session = boto3.Session(
        aws_access_key_id     = creds.get("aws_access_key_id"),
        aws_secret_access_key = creds.get("aws_secret_access_key"),
        region_name           = creds.get("region", "us-east-1"),
    )
    return session.client("glue")


def _airflow(creds: dict):
    """Returns an Airflow REST API session (requests.Session)."""
    import requests
    s = requests.Session()
    s.auth    = (creds["user"], creds["password"])
    s.headers = {"Content-Type": "application/json"}
    s.base_url = creds["base_url"].rstrip("/")
    return s


def _mlflow(creds: dict):
    import mlflow
    mlflow.set_tracking_uri(creds["tracking_uri"])
    if creds.get("username"):
        os.environ["MLFLOW_TRACKING_USERNAME"] = creds["username"]
        os.environ["MLFLOW_TRACKING_PASSWORD"] = creds["password"]
    return mlflow


def _great_expectations(creds: dict):
    import great_expectations as gx
    ctx = gx.get_context(context_root_dir=creds.get("context_dir", "."))
    return ctx


def _dbt(creds: dict):
    """Returns env dict to pass to dbt subprocess."""
    return {
        "DBT_PROFILES_DIR":     creds.get("profiles_dir", os.path.expanduser("~/.dbt")),
        "DBT_TARGET":           creds.get("target", "prod"),
        "SNOWFLAKE_ACCOUNT":    creds.get("snowflake_account", ""),
        "SNOWFLAKE_USER":       creds.get("snowflake_user", ""),
        "SNOWFLAKE_PASSWORD":   creds.get("snowflake_password", ""),
        "SNOWFLAKE_ROLE":       creds.get("snowflake_role", ""),
        "SNOWFLAKE_WAREHOUSE":  creds.get("snowflake_warehouse", ""),
        "SNOWFLAKE_DATABASE":   creds.get("snowflake_database", ""),
        "SNOWFLAKE_SCHEMA":     creds.get("snowflake_schema", ""),
    }


def _datahub(creds: dict):
    from datahub.ingestion.run.pipeline import Pipeline
    return {
        "server":  creds["server"],
        "token":   creds.get("token", ""),
        "Pipeline": Pipeline,
    }


def _kql(creds: dict):
    """Returns Azure Data Explorer KustoClient."""
    from azure.kusto.data import KustoClient, KustoConnectionStringBuilder
    if creds.get("use_aad_app"):
        kcsb = KustoConnectionStringBuilder.with_aad_application_key_authentication(
            connection_string = creds["cluster_url"],
            aad_app_id        = creds["client_id"],
            app_key           = creds["client_secret"],
            authority_id      = creds["tenant_id"],
        )
    else:
        kcsb = KustoConnectionStringBuilder.with_az_cli_authentication(creds["cluster_url"])
    return KustoClient(kcsb)


def _informatica(creds: dict):
    """Returns an Informatica IICS REST session."""
    import requests
    s   = requests.Session()
    r   = s.post(
        f"{creds['base_url']}/ma/api/v2/user/login",
        json={"@type": "login", "username": creds["user"], "password": creds["password"]},
    )
    r.raise_for_status()
    data = r.json()
    s.headers["icSessionId"] = data["userInfo"]["sessionId"]
    s.base_url = data["userInfo"]["serverUrl"]
    return s


def _talend(creds: dict):
    """Returns a Talend TMC REST session."""
    import requests
    s = requests.Session()
    s.headers.update({
        "Authorization": f"Bearer {creds['api_key']}",
        "Content-Type":  "application/json",
    })
    s.base_url = creds.get("base_url", "https://api.us.cloud.talend.com")
    return s


def _feast(creds: dict):
    """Returns a Feast FeatureStore."""
    from feast import FeatureStore
    return FeatureStore(repo_path=creds.get("repo_path", "."))


def _sagemaker(creds: dict):
    import boto3
    import sagemaker
    session = boto3.Session(region_name=creds.get("region", "us-east-1"))
    return sagemaker.Session(boto_session=session)


def _vertex(creds: dict):
    from google.cloud import aiplatform
    aiplatform.init(project=creds["project"], location=creds.get("location", "us-central1"))
    return aiplatform


def _azure_ml(creds: dict):
    from azure.ai.ml import MLClient
    from azure.identity import ClientSecretCredential
    credential = ClientSecretCredential(
        tenant_id     = creds["tenant_id"],
        client_id     = creds["client_id"],
        client_secret = creds["client_secret"],
    )
    return MLClient(
        credential      = credential,
        subscription_id = creds["subscription_id"],
        resource_group  = creds["resource_group"],
        workspace_name  = creds["workspace_name"],
    )


def _collibra(creds: dict):
    import requests
    s = requests.Session()
    s.auth    = (creds["user"], creds["password"])
    s.headers = {"Content-Type": "application/json"}
    s.base_url = creds["base_url"].rstrip("/")
    return s


# ── Registry ──────────────────────────────────────────────────────────────

CONNECTOR_REGISTRY = {
    # Platform name (case-insensitive key) → metadata + factory
    "snowflake": {
        "vault_service":  "snowflake",
        "required_keys":  ["account", "user"],
        "auth_options":   ["password", "private_key_path"],
        "factory":        _snowflake,
        "health_check":   "SELECT CURRENT_TIMESTAMP()",
        "docs":           "CONNECTIONS.md#snowflake",
    },
    "redshift": {
        "vault_service":  "redshift",
        "required_keys":  ["host", "database", "user", "password"],
        "factory":        _redshift,
        "health_check":   "SELECT 1",
        "docs":           "CONNECTIONS.md#redshift",
    },
    "bigquery": {
        "vault_service":  "bigquery",
        "required_keys":  ["project"],
        "factory":        _bigquery,
        "health_check":   None,   # use client.query("SELECT 1")
        "docs":           "CONNECTIONS.md#bigquery",
    },
    "databricks": {
        "vault_service":  "databricks",
        "required_keys":  ["host", "http_path", "token"],
        "factory":        _databricks,
        "health_check":   "SELECT 1",
        "docs":           "CONNECTIONS.md#databricks",
    },
    "postgresql": {
        "vault_service":  "postgresql",
        "required_keys":  ["host", "database", "user", "password"],
        "factory":        _postgres,
        "health_check":   "SELECT 1",
    },
    "mysql": {
        "vault_service":  "mysql",
        "required_keys":  ["host", "database", "user", "password"],
        "factory":        _mysql,
        "health_check":   "SELECT 1",
    },
    "sql server": {
        "vault_service":  "sqlserver",
        "required_keys":  ["host", "database", "user", "password"],
        "factory":        _sqlserver,
        "health_check":   "SELECT 1",
    },
    "kafka": {
        "vault_service":  "kafka",
        "required_keys":  ["bootstrap_servers"],
        "factory":        _kafka,
        "health_check":   None,  # list_topics()
        "docs":           "CONNECTIONS.md#kafka",
    },
    "kinesis": {
        "vault_service":  "aws",
        "required_keys":  ["region"],
        "factory":        _kinesis,
        "health_check":   None,
        "docs":           "CONNECTIONS.md#kinesis",
    },
    "s3": {
        "vault_service":  "aws",
        "required_keys":  ["region"],
        "factory":        _s3,
        "health_check":   None,
    },
    "glue": {
        "vault_service":  "aws",
        "required_keys":  ["region"],
        "factory":        _glue,
        "health_check":   None,
    },
    "airflow": {
        "vault_service":  "airflow",
        "required_keys":  ["base_url", "user", "password"],
        "factory":        _airflow,
        "health_check":   None,
    },
    "mlflow": {
        "vault_service":  "mlflow",
        "required_keys":  ["tracking_uri"],
        "factory":        _mlflow,
        "health_check":   None,
    },
    "great expectations": {
        "vault_service":  None,  # local config only
        "required_keys":  [],
        "factory":        _great_expectations,
        "health_check":   None,
    },
    "dbt": {
        "vault_service":  "snowflake",  # dbt uses Snowflake creds
        "required_keys":  [],
        "factory":        _dbt,
        "health_check":   None,
        "docs":           "CONNECTIONS.md#dbt",
    },
    "datahub": {
        "vault_service":  "datahub",
        "required_keys":  ["server"],
        "factory":        _datahub,
        "health_check":   None,
    },
    "azure data explorer": {
        "vault_service":  "kql",
        "required_keys":  ["cluster_url"],
        "factory":        _kql,
        "health_check":   None,
        "docs":           "CONNECTIONS.md#kql",
    },
    "kql": {
        "vault_service":  "kql",
        "required_keys":  ["cluster_url"],
        "factory":        _kql,
        "health_check":   None,
        "docs":           "CONNECTIONS.md#kql",
    },
    "informatica": {
        "vault_service":  "informatica",
        "required_keys":  ["base_url", "user", "password"],
        "factory":        _informatica,
        "health_check":   None,
        "docs":           "CONNECTIONS.md#informatica",
    },
    "talend": {
        "vault_service":  "talend",
        "required_keys":  ["api_key"],
        "factory":        _talend,
        "health_check":   None,
        "docs":           "CONNECTIONS.md#talend",
    },
    "feast": {
        "vault_service":  None,
        "required_keys":  ["repo_path"],
        "factory":        _feast,
        "health_check":   None,
    },
    "sagemaker": {
        "vault_service":  "aws",
        "required_keys":  ["region"],
        "factory":        _sagemaker,
        "health_check":   None,
    },
    "vertex ai": {
        "vault_service":  "gcp",
        "required_keys":  ["project"],
        "factory":        _vertex,
        "health_check":   None,
    },
    "azure ml": {
        "vault_service":  "azure_ml",
        "required_keys":  ["subscription_id", "resource_group", "workspace_name"],
        "factory":        _azure_ml,
        "health_check":   None,
    },
    "collibra": {
        "vault_service":  "collibra",
        "required_keys":  ["base_url", "user", "password"],
        "factory":        _collibra,
        "health_check":   None,
    },
}


class ConnectorRegistry:
    """
    Central connector factory.

    Usage:
        conn = ConnectorRegistry.connect("snowflake")
        conn = ConnectorRegistry.connect("kafka")
        conn = ConnectorRegistry.connect("dbt")   # returns env dict
    """

    @staticmethod
    def connect(platform: str, creds: dict = None):
        """
        Get a live connection for the named platform.

        If creds is not supplied, fetches from the Vault automatically.
        """
        key = platform.lower().strip()
        spec = CONNECTOR_REGISTRY.get(key)
        if not spec:
            # fuzzy match
            matches = [k for k in CONNECTOR_REGISTRY if key in k]
            if len(matches) == 1:
                spec = CONNECTOR_REGISTRY[matches[0]]
                key  = matches[0]
            elif len(matches) > 1:
                raise ValueError(f"Ambiguous platform '{platform}': matches {matches}")
            else:
                raise ValueError(f"Unknown platform '{platform}'. Available: {list(CONNECTOR_REGISTRY)}")

        if creds is None:
            service = spec.get("vault_service")
            if service:
                vault  = _vault()
                creds  = vault.get(service)
                if not creds:
                    raise RuntimeError(
                        f"No credentials found for service '{service}'. "
                        f"Run: python3 vault/vault.py set {service} '{{\"key\": \"value\"}}'"
                    )
            else:
                creds = {}

        return spec["factory"](creds)

    @staticmethod
    def info(platform: str = None) -> None:
        if platform:
            key  = platform.lower()
            spec = CONNECTOR_REGISTRY.get(key, {})
            print(f"\n  Platform : {key}")
            print(f"  Service  : {spec.get('vault_service', 'n/a')}")
            print(f"  Required : {spec.get('required_keys', [])}")
            print(f"  Docs     : {spec.get('docs', 'see CONNECTIONS.md')}")
        else:
            print(f"\n  {'Platform':<25} {'Vault Service':<20} Required keys")
            print("  " + "-" * 65)
            for name, spec in sorted(CONNECTOR_REGISTRY.items()):
                req = ", ".join(spec.get("required_keys", [])[:3])
                svc = spec.get("vault_service", "-")
                print(f"  {name:<25} {svc:<20} {req}")
            print(f"\n  Total platforms: {len(CONNECTOR_REGISTRY)}")


def get_connector(platform: str, creds: dict = None):
    """Shorthand for ConnectorRegistry.connect(platform, creds)."""
    return ConnectorRegistry.connect(platform, creds)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        ConnectorRegistry.info(sys.argv[1])
    else:
        ConnectorRegistry.info()
