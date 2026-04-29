"""
Agent definitions for AWS Bedrock multi-agent deployment.
Instructions are loaded from each agent's CLAUDE.md file.
"""

import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def load_instruction(agent_id: str) -> str:
    path = os.path.join(REPO_ROOT, "agents", agent_id, "CLAUDE.md")
    with open(path) as f:
        return f.read()


# Model used for all agents — Claude Sonnet 4.5 on Bedrock cross-region inference
FOUNDATION_MODEL = "us.anthropic.claude-sonnet-4-5-20251001-v1:0"

# Mayor is the supervisor; all others are sub-agents it orchestrates
AGENTS = [
    {
        "id":          "mayor",
        "name":        "mdw-mayor",
        "role":        "Global Orchestrator",
        "description": "Coordinates all agents, dispatches tasks, handles escalations. Routes work to the correct specialist based on domain and task type.",
        "supervisor":  True,   # SUPERVISOR_AND_EXECUTOR — can orchestrate AND execute
    },
    {
        "id":          "worker",
        "name":        "mdw-worker",
        "role":        "Task Executor",
        "description": "Executes scoped implementation tasks dispatched by the Mayor. Handles general coding, scripting, and analysis tasks.",
        "supervisor":  False,
    },
    {
        "id":          "monitor",
        "name":        "mdw-monitor",
        "role":        "Observability Agent",
        "description": "Runs data quality checks, detects anomalies, and compares data across pipeline layers. Alerts Mayor on failures.",
        "supervisor":  False,
    },
    {
        "id":          "refinery",
        "name":        "mdw-refinery",
        "role":        "Code Review Gate",
        "description": "Reviews and approves code changes before merge. Enforces quality standards across all code produced by worker agents.",
        "supervisor":  False,
    },
    {
        "id":          "data_engineer",
        "name":        "mdw-data-engineer",
        "role":        "Data Engineer",
        "description": "Builds ETL pipelines, Glue/Spark jobs, Kafka/Kinesis ingestion, and manages the S3 data lake architecture.",
        "supervisor":  False,
    },
    {
        "id":          "analytics_engineer",
        "name":        "mdw-analytics-engineer",
        "role":        "Analytics Engineer",
        "description": "Owns dbt models, star/snowflake schemas, Snowflake optimization, and the semantic/BI layer.",
        "supervisor":  False,
    },
    {
        "id":          "streaming_engineer",
        "name":        "mdw-streaming-engineer",
        "role":        "Streaming Engineer",
        "description": "Builds and maintains Kafka, Kinesis, and real-time CDC pipelines for event-driven data flows.",
        "supervisor":  False,
    },
    {
        "id":          "data_scientist",
        "name":        "mdw-data-scientist",
        "role":        "Data Scientist / ML Engineer",
        "description": "Trains ML models, manages feature stores, and deploys models via SageMaker and MLflow.",
        "supervisor":  False,
    },
    {
        "id":          "governance",
        "name":        "mdw-governance",
        "role":        "Data Governance",
        "description": "Manages Collibra/DataHub catalogs, enforces PII masking, GDPR compliance, and RBAC access control.",
        "supervisor":  False,
    },
    {
        "id":          "dataops",
        "name":        "mdw-dataops",
        "role":        "DataOps Engineer",
        "description": "Manages Airflow DAGs, CI/CD pipelines, cost optimization, and platform engineering.",
        "supervisor":  False,
    },
    {
        "id":          "cloud_infra",
        "name":        "mdw-cloud-infra",
        "role":        "Cloud Infrastructure",
        "description": "Provisions and manages Terraform IaC, VPC, IAM, S3, and all AWS compute resources.",
        "supervisor":  False,
    },
    {
        "id":          "data_quality",
        "name":        "mdw-data-quality",
        "role":        "Data Quality Agent",
        "description": "Runs Great Expectations suites, monitors SLAs, and maintains data quality dashboards.",
        "supervisor":  False,
    },
    {
        "id":          "reliability",
        "name":        "mdw-reliability",
        "role":        "Data Reliability / SRE",
        "description": "Manages incidents, pipeline monitoring, SLO tracking, and alerting across the data platform.",
        "supervisor":  False,
    },
    {
        "id":          "investigator",
        "name":        "mdw-investigator",
        "role":        "Pipeline Investigator",
        "description": "Investigates job failures, schema drift, data freshness issues, and unexpected null rates.",
        "supervisor":  False,
    },
    {
        "id":          "qa",
        "name":        "mdw-qa",
        "role":        "QA Agent",
        "description": "Generates test plans, test cases, sample data sets, runs QA suites, and produces lineage documentation.",
        "supervisor":  False,
    },
    {
        "id":          "cicd",
        "name":        "mdw-cicd",
        "role":        "CI/CD & Infrastructure Agent",
        "description": "Manages GitHub Actions workflows, Terraform VPC and data platform modules, IAM policies, and S3 bucket config.",
        "supervisor":  False,
    },
]

# Routing rules from config/routing.json — used to build Mayor's instruction
ROUTING_RULES = {
    "incident":      "reliability",
    "investigation": "investigator",
    "qa":            "qa",
    "infra":         "cicd",
    "review":        "refinery",
    "monitor":       "monitor",
    "etl_pipelines": "data_engineer",
    "data_lake":     "data_engineer",
    "cdc_streaming": "streaming_engineer",
    "event_streaming":"streaming_engineer",
    "dbt_modelling": "analytics_engineer",
    "data_warehouse":"analytics_engineer",
    "feature_engineering":"data_scientist",
    "model_training":"data_scientist",
    "mlops":         "data_scientist",
    "data_governance":"governance",
    "pii_masking":   "governance",
    "data_quality":  "data_quality",
    "pipeline_reliability":"reliability",
    "cloud_infra":   "cicd",
    "platform_engineering":"dataops",
    "cost_optimization":"dataops",
}
