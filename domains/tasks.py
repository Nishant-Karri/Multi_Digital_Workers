#!/usr/bin/env python3
"""
domains/tasks.py — Task Templates per Domain

Each template maps to a sequence of stages with standard steps.
Used by scheduler.py for task decomposition.
"""

TASK_TEMPLATES = {

    # ── Ingestion & Integration ────────────────────────────────────────────

    "etl_standard": {
        "domain": "batch_ingestion",
        "description": "Standard ETL: extract → validate → load → verify",
        "stages": [
            {"name": "design",   "steps": ["document source schema", "define target schema", "agree SLA + schedule"]},
            {"name": "extract",  "steps": ["connect to source", "extract sample", "validate row count + schema"]},
            {"name": "transform","steps": ["apply data type casts", "handle nulls", "deduplicate", "apply business rules"]},
            {"name": "load",     "steps": ["write to target table", "verify row counts match", "check null rates"]},
            {"name": "schedule", "steps": ["create Airflow/Glue DAG", "set up alerting", "document runbook"]},
        ],
    },

    "incremental_load": {
        "domain": "batch_ingestion",
        "description": "Incremental load using watermark or CDC",
        "stages": [
            {"name": "design",   "steps": ["identify watermark column", "define lookback window", "handle late arrivals"]},
            {"name": "implement","steps": ["read high-water mark", "extract delta rows", "upsert to target"]},
            {"name": "validate", "steps": ["count new rows", "check for gaps", "alert on zero-row runs"]},
        ],
    },

    "kafka_consumer": {
        "domain": "streaming_ingestion",
        "description": "Kafka → sink streaming consumer",
        "stages": [
            {"name": "setup",    "steps": ["configure consumer group", "set offset policy", "define schema registry"]},
            {"name": "build",    "steps": ["implement consumer loop", "parse + validate messages", "write to sink"]},
            {"name": "ops",      "steps": ["monitor consumer lag", "set lag alert threshold", "test rebalancing"]},
        ],
    },

    "kinesis_consumer": {
        "domain": "streaming_ingestion",
        "description": "AWS Kinesis → S3/Snowflake consumer",
        "stages": [
            {"name": "setup",    "steps": ["create Kinesis stream", "configure shard count", "set retention period"]},
            {"name": "build",    "steps": ["implement Kinesis Data Firehose or Lambda consumer", "write to S3/Snowflake"]},
            {"name": "ops",      "steps": ["monitor iterator age", "set CloudWatch alarms", "test shard splitting"]},
        ],
    },

    "rest_paginated": {
        "domain": "api_ingestion",
        "description": "Paginated REST API extractor",
        "stages": [
            {"name": "design",   "steps": ["map API endpoints", "handle auth (OAuth/key)", "identify pagination pattern"]},
            {"name": "build",    "steps": ["implement paginator", "rate-limit handling + retry", "write to staging"]},
            {"name": "validate", "steps": ["verify total row count", "check freshness", "test schema drift"]},
        ],
    },

    "cdc_full": {
        "domain": "database_replication",
        "description": "Full CDC replication from operational DB",
        "stages": [
            {"name": "setup",    "steps": ["enable binlog/WAL on source", "configure Debezium/DMS connector", "create target tables"]},
            {"name": "initial",  "steps": ["run snapshot load", "verify row count parity"]},
            {"name": "ongoing",  "steps": ["stream CDC events", "apply inserts/updates/deletes", "monitor lag < 30s"]},
        ],
    },

    # ── Transformation & Modeling ──────────────────────────────────────────

    "dbt_model_new": {
        "domain": "dbt_modeling",
        "description": "Create new dbt model from scratch",
        "stages": [
            {"name": "design",   "steps": ["define grain", "identify source tables", "sketch SELECT logic"]},
            {"name": "develop",  "steps": ["write model SQL", "add schema.yml with tests", "run dbt build --select model"]},
            {"name": "test",     "steps": ["run dbt test", "review row count + sample data", "check lineage in docs"]},
            {"name": "deploy",   "steps": ["PR review", "merge to main", "CI dbt run in prod"]},
        ],
    },

    "dbt_refactor": {
        "domain": "dbt_modeling",
        "description": "Refactor existing dbt model (grain change, logic fix, perf)",
        "stages": [
            {"name": "audit",    "steps": ["document current grain + logic", "identify downstream dependents"]},
            {"name": "refactor", "steps": ["rewrite SQL", "update schema.yml", "run comparison vs old model"]},
            {"name": "validate", "steps": ["row count delta < 0.1%", "key metrics unchanged", "downstream models pass"]},
            {"name": "deploy",   "steps": ["blue-green cutover or full refresh", "monitor post-deploy"]},
        ],
    },

    "spark_batch": {
        "domain": "spark_transformation",
        "description": "PySpark batch processing job",
        "stages": [
            {"name": "design",   "steps": ["identify input/output partitioning", "plan join strategy", "estimate DPU/cores"]},
            {"name": "develop",  "steps": ["write PySpark job", "unit test with pytest + small data", "optimize shuffle"]},
            {"name": "deploy",   "steps": ["package to Glue/EMR/Databricks", "set up job trigger", "test full run"]},
        ],
    },

    "glue_etl": {
        "domain": "spark_transformation",
        "description": "AWS Glue ETL job (landing → curated)",
        "stages": [
            {"name": "setup",    "steps": ["create Glue job + IAM role", "configure S3 paths + Glue catalog"]},
            {"name": "develop",  "steps": ["write Glue script (DynamicFrame)", "add dedup logic", "write to Iceberg/S3"]},
            {"name": "schedule", "steps": ["create Glue trigger or EventBridge rule", "test end-to-end", "add CloudWatch alarm"]},
        ],
    },

    # ── Analytics & Reporting ──────────────────────────────────────────────

    "dashboard_new": {
        "domain": "bi_report",
        "description": "New BI dashboard from scratch",
        "stages": [
            {"name": "discovery","steps": ["gather requirements from stakeholders", "identify data sources", "define KPIs"]},
            {"name": "data",     "steps": ["validate underlying tables", "write supporting SQL/dbt models if needed"]},
            {"name": "build",    "steps": ["build dashboard in Tableau/Power BI/Streamlit", "add filters + drill-downs"]},
            {"name": "publish",  "steps": ["peer review visuals", "share with stakeholders", "document refresh schedule"]},
        ],
    },

    "kql_query": {
        "domain": "kql_analytics",
        "description": "Azure Data Explorer / KQL query",
        "stages": [
            {"name": "design",   "steps": ["identify KQL table + time range", "define filter + aggregation logic"]},
            {"name": "develop",  "steps": ["write KQL query", "test in ADX web UI", "optimize with materialize()"]},
            {"name": "deploy",   "steps": ["save to ADX dashboard or alert rule", "document query purpose"]},
        ],
    },

    "eda_report": {
        "domain": "ad_hoc_analysis",
        "description": "Exploratory data analysis report",
        "stages": [
            {"name": "scope",    "steps": ["define question to answer", "identify relevant tables + time range"]},
            {"name": "explore",  "steps": ["profile row counts + distributions", "check for anomalies or outliers"]},
            {"name": "analyse",  "steps": ["segment + aggregate data", "build supporting charts"]},
            {"name": "present",  "steps": ["write findings doc", "highlight key insights + next actions"]},
        ],
    },

    # ── Machine Learning & AI ──────────────────────────────────────────────

    "feature_pipeline": {
        "domain": "feature_engineering",
        "description": "End-to-end feature pipeline to feature store",
        "stages": [
            {"name": "design",   "steps": ["define feature group + entity key", "identify raw source tables"]},
            {"name": "compute",  "steps": ["write feature SQL / PySpark", "backfill historical data", "validate distributions"]},
            {"name": "register", "steps": ["register feature group in Feast/Tecton", "document data lineage"]},
            {"name": "monitor",  "steps": ["set up drift detection", "alert on > 5% distribution shift"]},
        ],
    },

    "train_eval_deploy": {
        "domain": "model_training",
        "description": "Train, evaluate, and deploy ML model",
        "stages": [
            {"name": "data",     "steps": ["pull features from feature store", "split train/val/test", "inspect class balance"]},
            {"name": "train",    "steps": ["define model architecture", "train with cross-validation", "log metrics to MLflow"]},
            {"name": "eval",     "steps": ["evaluate on holdout set", "compare vs baseline", "generate SHAP/feature importance"]},
            {"name": "deploy",   "steps": ["register model in registry", "create inference endpoint", "A/B test vs current model"]},
        ],
    },

    "mlops_pipeline": {
        "domain": "mlops",
        "description": "Set up end-to-end MLOps CI/CD pipeline",
        "stages": [
            {"name": "infra",    "steps": ["provision SageMaker/Azure ML workspace", "set up model registry", "configure artifact store"]},
            {"name": "pipeline", "steps": ["define training pipeline steps", "add data validation gate", "add model evaluation gate"]},
            {"name": "cicd",     "steps": ["trigger pipeline on data freshness or schedule", "auto-register on pass", "alert on drift"]},
        ],
    },

    # ── Data Quality & Observability ───────────────────────────────────────

    "ge_suite_add": {
        "domain": "data_quality",
        "description": "Add Great Expectations suite for a table",
        "stages": [
            {"name": "profile",  "steps": ["auto-profile table with GE profiler", "review generated expectations"]},
            {"name": "curate",   "steps": ["remove noisy expectations", "add business-critical custom checks"]},
            {"name": "integrate","steps": ["add GE checkpoint to pipeline", "configure Slack/email on failure"]},
        ],
    },

    "dbt_test_add": {
        "domain": "data_quality",
        "description": "Add dbt tests to model",
        "stages": [
            {"name": "audit",    "steps": ["identify critical columns without tests"]},
            {"name": "add",      "steps": ["add not_null, unique, accepted_values, relationships tests in schema.yml"]},
            {"name": "run",      "steps": ["run dbt test --select model", "fix any failures", "PR + merge"]},
        ],
    },

    "profile_table": {
        "domain": "data_profiling",
        "description": "Statistical profile of a table",
        "stages": [
            {"name": "run",      "steps": ["execute observability/profiler.py on target table"]},
            {"name": "review",   "steps": ["inspect null rates, cardinality, distributions", "flag outlier columns"]},
            {"name": "act",      "steps": ["create data quality tickets for bad columns", "update schema docs"]},
        ],
    },

    "zscore_check": {
        "domain": "anomaly_detection",
        "description": "Z-score anomaly check on a time-series metric",
        "stages": [
            {"name": "baseline", "steps": ["compute rolling mean + std over lookback window"]},
            {"name": "detect",   "steps": ["compute z-score for today's value", "flag if |z| > threshold (default 3)"]},
            {"name": "alert",    "steps": ["send alert with metric value, z-score, and baseline"]},
        ],
    },

    # ── Data Governance ────────────────────────────────────────────────────

    "lineage_scan": {
        "domain": "data_lineage",
        "description": "Scan and document data lineage for a model or pipeline",
        "stages": [
            {"name": "scan",     "steps": ["run dbt docs generate or OpenLineage scanner"]},
            {"name": "map",      "steps": ["identify all upstream sources + downstream consumers"]},
            {"name": "document", "steps": ["export lineage graph to DataHub/Collibra", "flag orphaned models"]},
        ],
    },

    "pii_scan": {
        "domain": "data_privacy",
        "description": "Scan tables for PII columns",
        "stages": [
            {"name": "scan",     "steps": ["run pattern matching on column names + sample values"]},
            {"name": "review",   "steps": ["human review of flagged columns", "classify sensitivity level"]},
            {"name": "remediate","steps": ["apply masking or tokenization", "document in data catalog"]},
        ],
    },

    "rbac_review": {
        "domain": "access_control",
        "description": "Audit and clean up data access roles",
        "stages": [
            {"name": "audit",    "steps": ["list all role grants in Snowflake/AWS IAM"]},
            {"name": "review",   "steps": ["identify over-privileged roles", "check for orphan users"]},
            {"name": "remediate","steps": ["revoke excess grants", "implement least-privilege", "document changes"]},
        ],
    },

    # ── Infrastructure & DataOps ───────────────────────────────────────────

    "dag_new": {
        "domain": "pipeline_orchestration",
        "description": "Create new Airflow/Prefect/Dagster DAG",
        "stages": [
            {"name": "design",   "steps": ["define task dependencies", "choose trigger (schedule/sensor/manual)"]},
            {"name": "develop",  "steps": ["write DAG code", "add retries + SLA miss callbacks", "test locally"]},
            {"name": "deploy",   "steps": ["deploy to Airflow/Prefect/Dagster", "trigger test run", "verify task ordering"]},
        ],
    },

    "cicd_dbt": {
        "domain": "cicd_data",
        "description": "GitHub Actions CI for dbt project",
        "stages": [
            {"name": "setup",    "steps": ["create .github/workflows/dbt-ci.yml", "add Snowflake secrets to GitHub"]},
            {"name": "pipeline", "steps": ["dbt deps + compile on PR open", "dbt build --select state:modified+ on PR"]},
            {"name": "deploy",   "steps": ["dbt run on merge to main", "notify Slack on success/failure"]},
        ],
    },

    "cost_audit": {
        "domain": "cost_optimization",
        "description": "Audit data platform costs and find savings",
        "stages": [
            {"name": "collect",  "steps": ["pull Snowflake credit usage", "pull AWS Cost Explorer data", "pull Databricks DBU"]},
            {"name": "analyse",  "steps": ["identify top 10 cost drivers", "find idle warehouses/clusters", "find oversized resources"]},
            {"name": "act",      "steps": ["right-size warehouses", "add auto-suspend rules", "estimate savings"]},
        ],
    },

    # ── Migration & Integration ────────────────────────────────────────────

    "migration": {
        "domain": "data_migration",
        "description": "Platform migration (source → target)",
        "stages": [
            {"name": "discovery","steps": ["inventory all source objects (tables, views, jobs, users)"]},
            {"name": "design",   "steps": ["map source → target schema", "define cutover plan", "agree rollback strategy"]},
            {"name": "migrate",  "steps": ["migrate schema", "migrate historical data", "validate row counts + checksums"]},
            {"name": "cutover",  "steps": ["dual-write period", "verify parity", "cut traffic to new platform", "decommission old"]},
        ],
    },

    "reverse_etl_sync": {
        "domain": "reverse_etl",
        "description": "Warehouse → operational system sync",
        "stages": [
            {"name": "design",   "steps": ["define segment/audience SQL", "map to target system fields"]},
            {"name": "build",    "steps": ["configure Census/Hightouch sync or custom Python", "test with dry-run"]},
            {"name": "schedule", "steps": ["set sync frequency", "add row count alert", "test full sync"]},
        ],
    },

    "snowflake_share": {
        "domain": "data_sharing",
        "description": "Create Snowflake secure data share",
        "stages": [
            {"name": "design",   "steps": ["identify objects to share", "define consumer org/account", "review PII exposure"]},
            {"name": "create",   "steps": ["CREATE SHARE + GRANT on objects", "add consumer account", "test consumer access"]},
            {"name": "document", "steps": ["document data dictionary for shared objects", "agree refresh SLA"]},
        ],
    },
}


def get_template(name: str) -> dict:
    return TASK_TEMPLATES.get(name, {})


def templates_for_domain(domain: str) -> list:
    return [k for k, v in TASK_TEMPLATES.items() if v.get("domain") == domain]


def list_templates() -> None:
    print(f"\n{'Template':<30} {'Domain':<30} {'Stages'}")
    print("-" * 75)
    for name, t in sorted(TASK_TEMPLATES.items()):
        stages = ", ".join(s["name"] for s in t["stages"])
        print(f"  {name:<28} {t['domain']:<30} {stages}")
    print(f"\nTotal templates: {len(TASK_TEMPLATES)}")


if __name__ == "__main__":
    list_templates()
