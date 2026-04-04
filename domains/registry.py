#!/usr/bin/env python3
"""
domains/registry.py — Universal Data Domain Registry

Defines every category of data work the system can handle,
with task templates, required skills, and agent routing.
"""

DOMAIN_REGISTRY = {

    # ── Ingestion & Integration ───────────────────────────────────────────────
    "batch_ingestion": {
        "description": "Scheduled batch data loads from any source",
        "platforms":   ["Glue", "Informatica", "Talend", "dbt", "Python", "SSIS", "Spark"],
        "agent_role":  "data_engineer",
        "templates":   ["etl_standard", "full_load", "incremental_load", "cdc"],
        "checks":      ["row_count", "nulls", "duplicates", "freshness"],
        "examples":    ["Load Salesforce → Snowflake daily", "S3 Parquet → Iceberg hourly"],
    },
    "streaming_ingestion": {
        "description": "Real-time data streaming and event processing",
        "platforms":   ["Kafka", "Kinesis", "EventHub", "Pub/Sub", "Flink", "Spark Streaming"],
        "agent_role":  "streaming_engineer",
        "templates":   ["kafka_consumer", "kinesis_consumer", "event_processor"],
        "checks":      ["lag", "throughput", "error_rate", "freshness"],
        "examples":    ["Kafka topic → Snowflake streaming", "Kinesis → S3 → Glue"],
    },
    "api_ingestion": {
        "description": "REST/GraphQL/SOAP API data extraction",
        "platforms":   ["Python", "Informatica", "Talend", "Airbyte", "Fivetran"],
        "agent_role":  "data_engineer",
        "templates":   ["rest_paginated", "graphql_extract", "webhook_receiver"],
        "checks":      ["row_count", "freshness", "schema_drift"],
        "examples":    ["Salesforce API → Snowflake", "Stripe events → S3"],
    },
    "database_replication": {
        "description": "CDC and full replication from operational databases",
        "platforms":   ["Debezium", "DMS", "Striim", "Informatica", "Qlik Replicate"],
        "agent_role":  "data_engineer",
        "templates":   ["cdc_full", "cdc_incremental", "snapshot_replication"],
        "checks":      ["lag", "row_count", "key_match"],
        "examples":    ["MySQL CDC → Snowflake", "Oracle → S3 via DMS"],
    },

    # ── Transformation & Modeling ─────────────────────────────────────────────
    "dbt_modeling": {
        "description": "dbt model development, testing, and deployment",
        "platforms":   ["dbt", "Snowflake", "BigQuery", "Redshift", "Databricks"],
        "agent_role":  "analytics_engineer",
        "templates":   ["dbt_model_new", "dbt_refactor", "dbt_test_add", "dbt_snapshot"],
        "checks":      ["dbt_test", "row_count", "freshness", "schema_drift"],
        "examples":    ["Add new dim_product model", "Refactor FACT_ORDER grain"],
    },
    "spark_transformation": {
        "description": "PySpark / Scala Spark data processing jobs",
        "platforms":   ["Spark", "Glue", "Databricks", "EMR", "Dataproc"],
        "agent_role":  "data_engineer",
        "templates":   ["spark_batch", "spark_streaming", "glue_etl"],
        "checks":      ["row_count", "nulls", "freshness", "schema_drift"],
        "examples":    ["Glue landing→curated dedup", "Databricks feature engineering"],
    },
    "sql_transformation": {
        "description": "SQL-based data transformations and stored procedures",
        "platforms":   ["Snowflake", "BigQuery", "Redshift", "SQL Server", "PostgreSQL"],
        "agent_role":  "analytics_engineer",
        "templates":   ["sql_view", "sql_stored_proc", "sql_materialized"],
        "checks":      ["row_count", "nulls", "key_match"],
        "examples":    ["Create Snowflake view for reporting", "Stored proc for aggregation"],
    },
    "data_wrangling": {
        "description": "Ad-hoc data cleaning, enrichment, and reshaping",
        "platforms":   ["Python", "pandas", "Polars", "SQL"],
        "agent_role":  "data_engineer",
        "templates":   ["pandas_clean", "feature_engineer", "data_merge"],
        "checks":      ["nulls", "schema_drift", "row_count"],
        "examples":    ["Clean address data", "Merge two CSV sources"],
    },

    # ── Analytics & Reporting ─────────────────────────────────────────────────
    "bi_report": {
        "description": "Business Intelligence report and dashboard development",
        "platforms":   ["Tableau", "Power BI", "Looker", "Streamlit", "QuickSight"],
        "agent_role":  "analytics",
        "templates":   ["dashboard_new", "report_new", "kpi_add"],
        "checks":      ["data_freshness", "metric_accuracy"],
        "examples":    ["Build sales dashboard in Streamlit", "Add KPI to Power BI"],
    },
    "kql_analytics": {
        "description": "Azure Data Explorer / KQL queries and dashboards",
        "platforms":   ["Azure Data Explorer", "Azure Monitor", "Sentinel"],
        "agent_role":  "analytics",
        "templates":   ["kql_query", "kql_dashboard", "kql_alert"],
        "checks":      ["freshness", "query_performance"],
        "examples":    ["KQL query for log anomalies", "Azure Monitor alert rule"],
    },
    "ad_hoc_analysis": {
        "description": "Exploratory data analysis and one-off investigations",
        "platforms":   ["Python", "SQL", "Jupyter", "KQL"],
        "agent_role":  "analytics",
        "templates":   ["eda_report", "data_investigation", "metric_deep_dive"],
        "checks":      ["data_freshness"],
        "examples":    ["Investigate revenue drop last Tuesday", "Cohort analysis"],
    },

    # ── Machine Learning & AI ─────────────────────────────────────────────────
    "feature_engineering": {
        "description": "Feature store management and feature pipeline development",
        "platforms":   ["Python", "Spark", "Snowflake", "Feast", "Tecton"],
        "agent_role":  "data_scientist",
        "templates":   ["feature_pipeline", "feature_store_add", "feature_backfill"],
        "checks":      ["nulls", "distribution_drift", "freshness"],
        "examples":    ["Build customer churn features", "Backfill 12-month feature history"],
    },
    "model_training": {
        "description": "ML model development, training, and evaluation",
        "platforms":   ["Python", "scikit-learn", "XGBoost", "PyTorch", "SageMaker"],
        "agent_role":  "data_scientist",
        "templates":   ["train_eval_deploy", "hyperparameter_tune", "model_retrain"],
        "checks":      ["model_accuracy", "data_drift", "feature_importance"],
        "examples":    ["Train churn prediction model", "Retrain demand forecast weekly"],
    },
    "mlops": {
        "description": "ML pipeline CI/CD, model registry, and monitoring",
        "platforms":   ["SageMaker", "MLflow", "Vertex AI", "Azure ML", "Databricks MLflow"],
        "agent_role":  "data_scientist",
        "templates":   ["mlops_pipeline", "model_registry", "drift_monitor"],
        "checks":      ["model_drift", "prediction_drift", "data_quality"],
        "examples":    ["Set up SageMaker pipeline", "Add MLflow model registry"],
    },

    # ── Data Quality & Observability ──────────────────────────────────────────
    "data_quality": {
        "description": "Data quality rules, validation, and SLA enforcement",
        "platforms":   ["Great Expectations", "dbt tests", "Custom Python", "Informatica DQ"],
        "agent_role":  "data_quality",
        "templates":   ["ge_suite_add", "dbt_test_add", "quality_rule_add"],
        "checks":      ["nulls", "duplicates", "referential_integrity", "domain_validity"],
        "examples":    ["Add GE suite for orders table", "Enforce FK constraints in dbt"],
    },
    "data_profiling": {
        "description": "Statistical profiling, cardinality, distribution analysis",
        "platforms":   ["Python", "Great Expectations", "SQL", "Pandas Profiling"],
        "agent_role":  "data_quality",
        "templates":   ["profile_table", "profile_compare", "distribution_report"],
        "checks":      ["completeness", "uniqueness", "distribution"],
        "examples":    ["Profile all tables in NISHANT_WORKFLOW_TEST", "Compare last 7 days"],
    },
    "anomaly_detection": {
        "description": "Statistical anomaly detection on metrics and time series",
        "platforms":   ["Python", "SQL", "Z-score", "IQR", "Prophet"],
        "agent_role":  "data_quality",
        "templates":   ["zscore_check", "iqr_check", "trend_break"],
        "checks":      ["metric_deviation", "volume_spike", "freshness"],
        "examples":    ["Alert if daily orders drop 30%", "Detect revenue spike anomaly"],
    },

    # ── Data Governance ───────────────────────────────────────────────────────
    "data_lineage": {
        "description": "Track data flow from source to consumption",
        "platforms":   ["dbt docs", "OpenLineage", "Marquez", "DataHub", "Collibra"],
        "agent_role":  "governance",
        "templates":   ["lineage_scan", "lineage_report", "impact_analysis"],
        "checks":      ["lineage_coverage"],
        "examples":    ["Map lineage for FACT_ORDER", "Impact analysis for column rename"],
    },
    "data_catalog": {
        "description": "Metadata management, tagging, and discovery",
        "platforms":   ["DataHub", "Collibra", "Alation", "AWS Glue Catalog", "Snowflake"],
        "agent_role":  "governance",
        "templates":   ["catalog_scan", "metadata_enrich", "tag_apply"],
        "checks":      ["metadata_coverage"],
        "examples":    ["Catalog all Snowflake tables", "Tag PII columns"],
    },
    "data_privacy": {
        "description": "PII detection, masking, and compliance enforcement",
        "platforms":   ["Python", "AWS Macie", "Informatica DQ", "Custom SQL"],
        "agent_role":  "governance",
        "templates":   ["pii_scan", "pii_mask", "compliance_report"],
        "checks":      ["pii_exposure", "masking_coverage"],
        "examples":    ["Scan for PII in Snowflake", "Mask SSN in reporting layer"],
    },
    "access_control": {
        "description": "RBAC, column-level security, and row-level policies",
        "platforms":   ["Snowflake", "AWS IAM", "Azure RBAC", "dbt"],
        "agent_role":  "governance",
        "templates":   ["rbac_review", "column_masking", "row_policy"],
        "checks":      ["access_audit"],
        "examples":    ["Review Snowflake role grants", "Add row-level security to FACT_ORDER"],
    },

    # ── Infrastructure & DataOps ──────────────────────────────────────────────
    "pipeline_orchestration": {
        "description": "DAG/workflow orchestration setup and maintenance",
        "platforms":   ["Airflow", "Prefect", "Dagster", "Step Functions", "Glue Workflows"],
        "agent_role":  "dataops",
        "templates":   ["dag_new", "dag_refactor", "schedule_change"],
        "checks":      ["dag_health", "task_duration", "failure_rate"],
        "examples":    ["Build Airflow DAG for NWT pipeline", "Add retry logic to Glue job"],
    },
    "cloud_data_infra": {
        "description": "Cloud data infrastructure provisioning and maintenance",
        "platforms":   ["AWS", "Azure", "GCP", "Terraform", "CDK", "Pulumi"],
        "agent_role":  "cloud_infra",
        "templates":   ["s3_setup", "glue_job", "snowflake_warehouse", "iam_policy"],
        "checks":      ["cost", "performance", "availability"],
        "examples":    ["Provision Glue job for new source", "Scale Snowflake warehouse"],
    },
    "cicd_data": {
        "description": "CI/CD pipelines for data code (dbt, Spark, SQL)",
        "platforms":   ["GitHub Actions", "GitLab CI", "Jenkins", "CodePipeline"],
        "agent_role":  "dataops",
        "templates":   ["cicd_dbt", "cicd_spark", "cicd_sql"],
        "checks":      ["test_coverage", "build_time", "deployment_success"],
        "examples":    ["Add dbt CI checks to GitHub Actions", "Auto-deploy on merge"],
    },
    "cost_optimization": {
        "description": "Data platform cost analysis and optimization",
        "platforms":   ["Snowflake", "AWS", "Azure", "GCP", "Databricks"],
        "agent_role":  "cloud_infra",
        "templates":   ["cost_audit", "warehouse_right_size", "storage_optimize"],
        "checks":      ["cost_trend", "query_efficiency"],
        "examples":    ["Reduce Snowflake credits 20%", "Right-size Glue DPU allocation"],
    },

    # ── Migration & Integration ───────────────────────────────────────────────
    "data_migration": {
        "description": "Platform migrations and large-scale data moves",
        "platforms":   ["Python", "Spark", "Informatica", "AWS DMS", "Snowpipe"],
        "agent_role":  "data_engineer",
        "templates":   ["migration"],
        "checks":      ["row_count", "key_match", "checksum", "freshness"],
        "examples":    ["Oracle → Snowflake migration", "On-prem HDFS → S3"],
    },
    "reverse_etl": {
        "description": "Push data from warehouse back to operational systems",
        "platforms":   ["Census", "Hightouch", "Python", "Informatica"],
        "agent_role":  "data_engineer",
        "templates":   ["reverse_etl_sync"],
        "checks":      ["row_count", "freshness", "key_match"],
        "examples":    ["Sync Snowflake segments → Salesforce", "Push scores → HubSpot"],
    },
    "data_sharing": {
        "description": "Secure data sharing between organizations or platforms",
        "platforms":   ["Snowflake Data Sharing", "Delta Sharing", "AWS Clean Rooms"],
        "agent_role":  "governance",
        "templates":   ["snowflake_share", "delta_share"],
        "checks":      ["access_audit", "row_count"],
        "examples":    ["Create Snowflake secure share", "Set up Delta Sharing endpoint"],
    },
}


def get_domain(name: str) -> dict:
    return DOMAIN_REGISTRY.get(name, {})


def domains_for_agent(agent_role: str) -> list:
    return [name for name, d in DOMAIN_REGISTRY.items() if d.get("agent_role") == agent_role]


def domains_for_platform(platform: str) -> list:
    platform_lower = platform.lower()
    return [
        name for name, d in DOMAIN_REGISTRY.items()
        if any(platform_lower in p.lower() for p in d.get("platforms", []))
    ]


def classify_task_domain(title: str, description: str = "") -> str:
    text = (title + " " + description).lower()
    scores = {}
    for domain, cfg in DOMAIN_REGISTRY.items():
        score = 0
        for platform in cfg.get("platforms", []):
            if platform.lower() in text:
                score += 3
        for example in cfg.get("examples", []):
            for word in example.lower().split():
                if len(word) > 4 and word in text:
                    score += 1
        if any(t in text for t in cfg.get("templates", [])):
            score += 2
        scores[domain] = score
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "batch_ingestion"


def print_registry():
    categories = {
        "Ingestion & Integration":     ["batch_ingestion","streaming_ingestion","api_ingestion","database_replication"],
        "Transformation & Modeling":   ["dbt_modeling","spark_transformation","sql_transformation","data_wrangling"],
        "Analytics & Reporting":       ["bi_report","kql_analytics","ad_hoc_analysis"],
        "Machine Learning & AI":       ["feature_engineering","model_training","mlops"],
        "Data Quality & Observability":["data_quality","data_profiling","anomaly_detection"],
        "Data Governance":             ["data_lineage","data_catalog","data_privacy","access_control"],
        "Infrastructure & DataOps":    ["pipeline_orchestration","cloud_data_infra","cicd_data","cost_optimization"],
        "Migration & Integration":     ["data_migration","reverse_etl","data_sharing"],
    }
    print("\n" + "="*60)
    print("  Data Domain Registry — Supported Capabilities")
    print("="*60)
    for cat, domains in categories.items():
        print(f"\n  {cat}")
        for d in domains:
            cfg = DOMAIN_REGISTRY[d]
            print(f"    · {d:30s} → {cfg['agent_role']}")
    print(f"\n  Total domains: {len(DOMAIN_REGISTRY)}")
    print("="*60)


if __name__ == "__main__":
    print_registry()
