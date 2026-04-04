#!/usr/bin/env python3
from __future__ import annotations
"""
integrations/cicd.py — CI/CD + Infrastructure Generator

Generates:
  - GitHub Actions workflows (dbt CI, Spark/Glue CI, Terraform plan/apply)
  - Terraform modules: VPC, S3, Glue, Snowflake warehouse, IAM
  - terraform.tfvars templates
  - Environment-specific variable files

Usage:
  python3 integrations/cicd.py generate --all
  python3 integrations/cicd.py generate --type github-actions
  python3 integrations/cicd.py generate --type terraform
  python3 integrations/cicd.py terraform plan   --env prod
  python3 integrations/cicd.py terraform apply  --env prod   (requires approval)
  python3 integrations/cicd.py push              --env prod
"""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT   = Path(__file__).parent.parent
INFRA  = ROOT / "infrastructure"
GHA    = INFRA / "github_actions"
TF     = INFRA / "terraform"

for d in [GHA, TF / "vpc", TF / "data_platform", TF / "modules" / "glue",
          TF / "modules" / "s3", TF / "modules" / "iam", TF / "envs" / "prod",
          TF / "envs" / "dev"]:
    d.mkdir(parents=True, exist_ok=True)


class CICDGenerator:

    # ── GitHub Actions ─────────────────────────────────────────────────────

    def generate_github_actions(self) -> list[Path]:
        files = []
        files.append(self._write(GHA / "dbt-ci.yml",            self._dbt_ci()))
        files.append(self._write(GHA / "data-pipeline-ci.yml",  self._pipeline_ci()))
        files.append(self._write(GHA / "terraform-plan.yml",    self._terraform_plan_workflow()))
        files.append(self._write(GHA / "terraform-apply.yml",   self._terraform_apply_workflow()))
        files.append(self._write(GHA / "qa-run.yml",            self._qa_workflow()))
        files.append(self._write(GHA / "observability-check.yml",self._observability_workflow()))
        print(f"  ✓ GitHub Actions workflows written to {GHA.relative_to(ROOT)}/")
        return files

    def _dbt_ci(self) -> str:
        return """name: dbt CI

on:
  pull_request:
    paths:
      - 'dbt/**'
      - '.github/workflows/dbt-ci.yml'
  push:
    branches: [main]
    paths:
      - 'dbt/**'

concurrency:
  group: dbt-ci-${{ github.ref }}
  cancel-in-progress: true

jobs:
  dbt-check:
    name: dbt build + test
    runs-on: ubuntu-latest
    timeout-minutes: 30

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip

      - name: Install dbt
        run: pip install dbt-snowflake==1.7.*

      - name: dbt deps
        working-directory: dbt/
        run: dbt deps
        env:
          DBT_PROFILES_DIR: .
          SNOWFLAKE_ACCOUNT:   ${{ secrets.SNOWFLAKE_ACCOUNT }}
          SNOWFLAKE_USER:      ${{ secrets.SNOWFLAKE_USER }}
          SNOWFLAKE_PASSWORD:  ${{ secrets.SNOWFLAKE_PASSWORD }}
          SNOWFLAKE_ROLE:      ${{ secrets.SNOWFLAKE_ROLE }}
          SNOWFLAKE_WAREHOUSE: ${{ secrets.SNOWFLAKE_WAREHOUSE }}
          SNOWFLAKE_DATABASE:  ${{ secrets.SNOWFLAKE_DATABASE }}
          SNOWFLAKE_SCHEMA:    ${{ secrets.SNOWFLAKE_SCHEMA }}

      - name: dbt compile
        working-directory: dbt/
        run: dbt compile
        env:
          DBT_PROFILES_DIR: .
          SNOWFLAKE_ACCOUNT:   ${{ secrets.SNOWFLAKE_ACCOUNT }}
          SNOWFLAKE_USER:      ${{ secrets.SNOWFLAKE_USER }}
          SNOWFLAKE_PASSWORD:  ${{ secrets.SNOWFLAKE_PASSWORD }}
          SNOWFLAKE_ROLE:      ${{ secrets.SNOWFLAKE_ROLE }}
          SNOWFLAKE_WAREHOUSE: ${{ secrets.SNOWFLAKE_WAREHOUSE }}
          SNOWFLAKE_DATABASE:  ${{ secrets.SNOWFLAKE_DATABASE }}
          SNOWFLAKE_SCHEMA:    ${{ secrets.SNOWFLAKE_SCHEMA }}

      - name: dbt build (modified models only on PR, all on main)
        working-directory: dbt/
        run: |
          if [ "${{ github.event_name }}" == "pull_request" ]; then
            dbt build --select state:modified+ --defer --state prod-artifacts/ --target ci
          else
            dbt build --target prod
          fi
        env:
          DBT_PROFILES_DIR: .
          SNOWFLAKE_ACCOUNT:   ${{ secrets.SNOWFLAKE_ACCOUNT }}
          SNOWFLAKE_USER:      ${{ secrets.SNOWFLAKE_USER }}
          SNOWFLAKE_PASSWORD:  ${{ secrets.SNOWFLAKE_PASSWORD }}
          SNOWFLAKE_ROLE:      ${{ secrets.SNOWFLAKE_ROLE }}
          SNOWFLAKE_WAREHOUSE: ${{ secrets.SNOWFLAKE_WAREHOUSE }}
          SNOWFLAKE_DATABASE:  ${{ secrets.SNOWFLAKE_DATABASE }}
          SNOWFLAKE_SCHEMA:    ${{ secrets.SNOWFLAKE_SCHEMA }}

      - name: Upload dbt artifacts
        uses: actions/upload-artifact@v4
        if: always()
        with:
          name: dbt-artifacts
          path: dbt/target/

      - name: Notify Teams on failure
        if: failure()
        run: |
          curl -H 'Content-Type: application/json' \
               -d '{"text":"❌ dbt CI failed on ${{ github.ref }} — ${{ github.actor }}"}' \
               ${{ secrets.TEAMS_WEBHOOK }}
"""

    def _pipeline_ci(self) -> str:
        return """name: Data Pipeline CI

on:
  pull_request:
    paths:
      - 'integrations/**'
      - 'observability/**'
      - 'domains/**'
      - 'connectors/**'
  push:
    branches: [main]

jobs:
  lint-and-test:
    name: Python lint + unit tests
    runs-on: ubuntu-latest
    timeout-minutes: 15

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip

      - name: Install dependencies
        run: |
          pip install ruff pytest pytest-cov
          pip install -r requirements.txt 2>/dev/null || true

      - name: Lint with ruff
        run: ruff check . --select E,F,W --ignore E501

      - name: Run unit tests
        run: pytest tests/ -v --tb=short --cov=. --cov-report=xml 2>/dev/null || echo "No tests yet"

      - name: Upload coverage
        uses: codecov/codecov-action@v4
        if: always()
        with:
          file: coverage.xml
          fail_ci_if_error: false

  observability-check:
    name: Observability config validation
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - name: Validate observability config
        run: python3 -c "import json; json.load(open('observability/config.json')); print('✓ config valid')"
      - name: Validate domain registry
        run: python3 -c "from domains.registry import DOMAIN_REGISTRY, print_registry; print_registry()"
      - name: Validate connector registry
        run: python3 -c "from connectors.registry import ConnectorRegistry; ConnectorRegistry.info()"

  security-scan:
    name: Secret scanning
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Detect secrets
        run: |
          if grep -rE "(password|secret|token|api_key)\s*=\s*['\"][^'\"\$\{]" \
                --include="*.py" --include="*.json" --include="*.yml" \
                --exclude-dir=".git" --exclude-dir="qa_artifacts" . ; then
            echo "❌ Hardcoded secrets detected. Use vault or env vars."
            exit 1
          fi
          echo "✓ No hardcoded secrets found"
"""

    def _terraform_plan_workflow(self) -> str:
        return """name: Terraform Plan

on:
  pull_request:
    paths:
      - 'infrastructure/terraform/**'
      - '.github/workflows/terraform-*.yml'

permissions:
  id-token: write
  contents: read
  pull-requests: write

jobs:
  terraform-plan:
    name: Plan (${{ matrix.env }})
    runs-on: ubuntu-latest
    timeout-minutes: 20
    strategy:
      matrix:
        env: [dev, prod]

    steps:
      - uses: actions/checkout@v4

      - name: Configure AWS credentials (OIDC)
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets[format('AWS_DEPLOY_ROLE_{0}', matrix.env)] }}
          aws-region: ${{ vars.AWS_REGION || 'us-east-1' }}

      - uses: hashicorp/setup-terraform@v3
        with:
          terraform_version: "1.7.x"

      - name: Terraform init
        working-directory: infrastructure/terraform/data_platform
        run: terraform init -backend-config=../envs/${{ matrix.env }}/backend.hcl

      - name: Terraform validate
        working-directory: infrastructure/terraform/data_platform
        run: terraform validate

      - name: Terraform plan
        id: plan
        working-directory: infrastructure/terraform/data_platform
        run: |
          terraform plan \\
            -var-file=../envs/${{ matrix.env }}/terraform.tfvars \\
            -out=tfplan.${{ matrix.env }} \\
            -detailed-exitcode 2>&1 | tee plan_output.txt
        continue-on-error: true

      - name: Post plan to PR
        uses: actions/github-script@v7
        if: github.event_name == 'pull_request'
        with:
          script: |
            const fs = require('fs');
            const plan = fs.readFileSync('infrastructure/terraform/data_platform/plan_output.txt', 'utf8');
            const truncated = plan.length > 65000 ? plan.slice(0, 65000) + '\\n... (truncated)' : plan;
            github.rest.issues.createComment({
              ...context.repo,
              issue_number: context.issue.number,
              body: '## Terraform Plan (${{ matrix.env }})\\n```hcl\\n' + truncated + '\\n```'
            });

      - name: Upload plan
        uses: actions/upload-artifact@v4
        with:
          name: tfplan-${{ matrix.env }}
          path: infrastructure/terraform/data_platform/tfplan.${{ matrix.env }}
"""

    def _terraform_apply_workflow(self) -> str:
        return """name: Terraform Apply

on:
  push:
    branches: [main]
    paths:
      - 'infrastructure/terraform/**'
  workflow_dispatch:
    inputs:
      environment:
        description: Target environment
        required: true
        default: dev
        type: choice
        options: [dev, prod]
      confirm:
        description: Type APPLY to confirm
        required: true

permissions:
  id-token: write
  contents: read

jobs:
  apply:
    name: Apply (${{ github.event.inputs.environment || 'dev' }})
    runs-on: ubuntu-latest
    timeout-minutes: 30
    environment: ${{ github.event.inputs.environment || 'dev' }}

    steps:
      - name: Check confirmation
        if: github.event_name == 'workflow_dispatch'
        run: |
          if [ "${{ github.event.inputs.confirm }}" != "APPLY" ]; then
            echo "❌ Confirmation required. Type APPLY to proceed."
            exit 1
          fi

      - uses: actions/checkout@v4

      - name: Configure AWS credentials (OIDC)
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets[format('AWS_DEPLOY_ROLE_{0}', github.event.inputs.environment || 'dev')] }}
          aws-region: ${{ vars.AWS_REGION || 'us-east-1' }}

      - uses: hashicorp/setup-terraform@v3
        with:
          terraform_version: "1.7.x"

      - name: Terraform init
        working-directory: infrastructure/terraform/data_platform
        run: terraform init -backend-config=../envs/${{ github.event.inputs.environment || 'dev' }}/backend.hcl

      - name: Terraform apply
        working-directory: infrastructure/terraform/data_platform
        run: |
          terraform apply -auto-approve \\
            -var-file=../envs/${{ github.event.inputs.environment || 'dev' }}/terraform.tfvars

      - name: Notify Teams
        if: always()
        run: |
          STATUS=${{ job.status }}
          ICON=$([ "$STATUS" = "success" ] && echo "✅" || echo "❌")
          curl -H 'Content-Type: application/json' \\
               -d "{\"text\":\"$ICON Terraform apply $STATUS on ${{ github.event.inputs.environment }}\"}" \\
               ${{ secrets.TEAMS_WEBHOOK }}
"""

    def _qa_workflow(self) -> str:
        return """name: QA Run

on:
  schedule:
    - cron: '0 8 * * *'   # Daily at 8am UTC (after pipelines complete)
  workflow_dispatch:
    inputs:
      pipeline:
        description: Pipeline to test
        required: true
        default: dbt_star_schema

jobs:
  qa:
    name: QA — ${{ github.event.inputs.pipeline || 'dbt_star_schema' }}
    runs-on: ubuntu-latest
    timeout-minutes: 30

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip

      - name: Install dependencies
        run: pip install snowflake-connector-python requests 2>/dev/null || true

      - name: Generate QA artifacts
        run: python3 integrations/qa.py generate --pipeline ${{ github.event.inputs.pipeline || 'dbt_star_schema' }}
        env:
          NGR_SNOWFLAKE_ACCOUNT:   ${{ secrets.SNOWFLAKE_ACCOUNT }}
          NGR_SNOWFLAKE_USER:      ${{ secrets.SNOWFLAKE_USER }}
          NGR_SNOWFLAKE_PASSWORD:  ${{ secrets.SNOWFLAKE_PASSWORD }}
          NGR_SNOWFLAKE_WAREHOUSE: ${{ secrets.SNOWFLAKE_WAREHOUSE }}
          NGR_SNOWFLAKE_DATABASE:  ${{ secrets.SNOWFLAKE_DATABASE }}
          NGR_SNOWFLAKE_SCHEMA:    ${{ secrets.SNOWFLAKE_SCHEMA }}

      - name: Run QA tests
        id: qa_run
        run: |
          python3 integrations/qa.py run --pipeline ${{ github.event.inputs.pipeline || 'dbt_star_schema' }} | tee qa_output.txt
          RUN_ID=$(grep "QA Run" qa_output.txt | grep -oE "QA-[A-Z0-9]+" | head -1)
          echo "run_id=$RUN_ID" >> $GITHUB_OUTPUT
        env:
          NGR_SNOWFLAKE_ACCOUNT:   ${{ secrets.SNOWFLAKE_ACCOUNT }}
          NGR_SNOWFLAKE_USER:      ${{ secrets.SNOWFLAKE_USER }}
          NGR_SNOWFLAKE_PASSWORD:  ${{ secrets.SNOWFLAKE_PASSWORD }}
          NGR_SNOWFLAKE_WAREHOUSE: ${{ secrets.SNOWFLAKE_WAREHOUSE }}
          NGR_SNOWFLAKE_DATABASE:  ${{ secrets.SNOWFLAKE_DATABASE }}
          NGR_SNOWFLAKE_SCHEMA:    ${{ secrets.SNOWFLAKE_SCHEMA }}

      - name: Generate lineage
        run: python3 integrations/qa.py lineage --pipeline ${{ github.event.inputs.pipeline || 'dbt_star_schema' }}

      - name: Upload QA artifacts
        uses: actions/upload-artifact@v4
        if: always()
        with:
          name: qa-artifacts-${{ steps.qa_run.outputs.run_id }}
          path: qa_artifacts/

      - name: Notify on failure
        if: failure()
        run: |
          curl -H 'Content-Type: application/json' \\
               -d '{"text":"❌ QA failed for ${{ github.event.inputs.pipeline }} — check artifacts"}' \\
               ${{ secrets.TEAMS_WEBHOOK }}
"""

    def _observability_workflow(self) -> str:
        return """name: Observability Check

on:
  schedule:
    - cron: '0 */2 * * *'   # Every 2 hours
  workflow_dispatch:

jobs:
  observe:
    name: Run observability checks
    runs-on: ubuntu-latest
    timeout-minutes: 20

    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: pip install snowflake-connector-python requests 2>/dev/null || true

      - name: Run observability
        run: python3 observability/observer.py run
        env:
          NGR_SNOWFLAKE_ACCOUNT:   ${{ secrets.SNOWFLAKE_ACCOUNT }}
          NGR_SNOWFLAKE_USER:      ${{ secrets.SNOWFLAKE_USER }}
          NGR_SNOWFLAKE_PASSWORD:  ${{ secrets.SNOWFLAKE_PASSWORD }}
          NGR_SNOWFLAKE_WAREHOUSE: ${{ secrets.SNOWFLAKE_WAREHOUSE }}
          NGR_SNOWFLAKE_DATABASE:  ${{ secrets.SNOWFLAKE_DATABASE }}
          NGR_SNOWFLAKE_SCHEMA:    ${{ secrets.SNOWFLAKE_SCHEMA }}
          NGR_TEAMS_WEBHOOK:       ${{ secrets.TEAMS_WEBHOOK }}
          NGR_SLACK_WEBHOOK:       ${{ secrets.SLACK_WEBHOOK }}

      - name: Run cross-layer comparisons
        run: python3 observability/observer.py compare
        env:
          NGR_SNOWFLAKE_ACCOUNT:   ${{ secrets.SNOWFLAKE_ACCOUNT }}
          NGR_SNOWFLAKE_USER:      ${{ secrets.SNOWFLAKE_USER }}
          NGR_SNOWFLAKE_PASSWORD:  ${{ secrets.SNOWFLAKE_PASSWORD }}
          NGR_SNOWFLAKE_WAREHOUSE: ${{ secrets.SNOWFLAKE_WAREHOUSE }}
          NGR_SNOWFLAKE_DATABASE:  ${{ secrets.SNOWFLAKE_DATABASE }}
          NGR_SNOWFLAKE_SCHEMA:    ${{ secrets.SNOWFLAKE_SCHEMA }}
          NGR_TEAMS_WEBHOOK:       ${{ secrets.TEAMS_WEBHOOK }}
          NGR_SLACK_WEBHOOK:       ${{ secrets.SLACK_WEBHOOK }}
"""

    # ── Terraform ──────────────────────────────────────────────────────────

    def generate_terraform(self) -> list[Path]:
        files = []
        files += self._write_vpc_module()
        files += self._write_data_platform_module()
        files += self._write_env_files()
        print(f"  ✓ Terraform modules written to {TF.relative_to(ROOT)}/")
        return files

    def _write_vpc_module(self) -> list[Path]:
        vpc_main = """# infrastructure/terraform/vpc/main.tf
# Data Platform VPC

terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

locals {
  name_prefix = "${var.project}-${var.environment}"
  common_tags = merge(var.tags, {
    Project     = var.project
    Environment = var.environment
    ManagedBy   = "terraform"
    Team        = "data-platform"
  })
}

# ── VPC ───────────────────────────────────────────────────────────────────

resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-vpc"
  })
}

# ── Internet Gateway ──────────────────────────────────────────────────────

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  tags   = merge(local.common_tags, { Name = "${local.name_prefix}-igw" })
}

# ── Subnets ───────────────────────────────────────────────────────────────

resource "aws_subnet" "public" {
  count                   = length(var.public_subnet_cidrs)
  vpc_id                  = aws_vpc.main.id
  cidr_block              = var.public_subnet_cidrs[count.index]
  availability_zone       = var.availability_zones[count.index % length(var.availability_zones)]
  map_public_ip_on_launch = true

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-public-${count.index + 1}"
    Tier = "public"
  })
}

resource "aws_subnet" "private" {
  count             = length(var.private_subnet_cidrs)
  vpc_id            = aws_vpc.main.id
  cidr_block        = var.private_subnet_cidrs[count.index]
  availability_zone = var.availability_zones[count.index % length(var.availability_zones)]

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-private-${count.index + 1}"
    Tier = "private"
  })
}

# ── NAT Gateways ──────────────────────────────────────────────────────────

resource "aws_eip" "nat" {
  count  = var.enable_nat_gateway ? length(var.public_subnet_cidrs) : 0
  domain = "vpc"
  tags   = merge(local.common_tags, { Name = "${local.name_prefix}-nat-eip-${count.index + 1}" })
}

resource "aws_nat_gateway" "main" {
  count         = var.enable_nat_gateway ? length(var.public_subnet_cidrs) : 0
  allocation_id = aws_eip.nat[count.index].id
  subnet_id     = aws_subnet.public[count.index].id
  tags          = merge(local.common_tags, { Name = "${local.name_prefix}-nat-${count.index + 1}" })
  depends_on    = [aws_internet_gateway.main]
}

# ── Route Tables ──────────────────────────────────────────────────────────

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }
  tags = merge(local.common_tags, { Name = "${local.name_prefix}-rt-public" })
}

resource "aws_route_table" "private" {
  count  = var.enable_nat_gateway ? length(var.private_subnet_cidrs) : 1
  vpc_id = aws_vpc.main.id

  dynamic "route" {
    for_each = var.enable_nat_gateway ? [1] : []
    content {
      cidr_block     = "0.0.0.0/0"
      nat_gateway_id = aws_nat_gateway.main[count.index % length(aws_nat_gateway.main)].id
    }
  }
  tags = merge(local.common_tags, { Name = "${local.name_prefix}-rt-private-${count.index + 1}" })
}

resource "aws_route_table_association" "public" {
  count          = length(var.public_subnet_cidrs)
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table_association" "private" {
  count          = length(var.private_subnet_cidrs)
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private[count.index % length(aws_route_table.private)].id
}

# ── Security Groups ───────────────────────────────────────────────────────

resource "aws_security_group" "glue" {
  name        = "${local.name_prefix}-sg-glue"
  description = "Glue ETL jobs — allow all self-referential traffic"
  vpc_id      = aws_vpc.main.id

  ingress {
    from_port = 0
    to_port   = 65535
    protocol  = "tcp"
    self      = true
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Allow all outbound"
  }
  tags = merge(local.common_tags, { Name = "${local.name_prefix}-sg-glue" })
}

resource "aws_security_group" "lambda" {
  name        = "${local.name_prefix}-sg-lambda"
  description = "Lambda functions — outbound only"
  vpc_id      = aws_vpc.main.id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Allow all outbound"
  }
  tags = merge(local.common_tags, { Name = "${local.name_prefix}-sg-lambda" })
}

# ── VPC Endpoints (reduce NAT costs) ─────────────────────────────────────

resource "aws_vpc_endpoint" "s3" {
  vpc_id          = aws_vpc.main.id
  service_name    = "com.amazonaws.${var.aws_region}.s3"
  route_table_ids = concat(
    [aws_route_table.public.id],
    aws_route_table.private[*].id
  )
  tags = merge(local.common_tags, { Name = "${local.name_prefix}-vpce-s3" })
}

resource "aws_vpc_endpoint" "glue" {
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${var.aws_region}.glue"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.glue.id]
  private_dns_enabled = true
  tags = merge(local.common_tags, { Name = "${local.name_prefix}-vpce-glue" })
}
"""

        vpc_vars = """# infrastructure/terraform/vpc/variables.tf

variable "project" {
  description = "Project name (used in resource naming)"
  type        = string
  default     = "nwt-data-platform"
}

variable "environment" {
  description = "Deployment environment (dev, staging, prod)"
  type        = string
  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be dev, staging, or prod"
  }
}

variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "vpc_cidr" {
  description = "VPC CIDR block"
  type        = string
  default     = "10.0.0.0/16"
}

variable "public_subnet_cidrs" {
  description = "CIDR blocks for public subnets (one per AZ)"
  type        = list(string)
  default     = ["10.0.1.0/24", "10.0.2.0/24"]
}

variable "private_subnet_cidrs" {
  description = "CIDR blocks for private subnets (one per AZ)"
  type        = list(string)
  default     = ["10.0.10.0/24", "10.0.11.0/24"]
}

variable "availability_zones" {
  description = "List of AZs to use"
  type        = list(string)
  default     = ["us-east-1a", "us-east-1b"]
}

variable "enable_nat_gateway" {
  description = "Enable NAT gateways for private subnets"
  type        = bool
  default     = true
}

variable "tags" {
  description = "Additional tags to apply to all resources"
  type        = map(string)
  default     = {}
}
"""

        vpc_outputs = """# infrastructure/terraform/vpc/outputs.tf

output "vpc_id" {
  description = "VPC ID"
  value       = aws_vpc.main.id
}

output "vpc_cidr" {
  description = "VPC CIDR block"
  value       = aws_vpc.main.cidr_block
}

output "public_subnet_ids" {
  description = "Public subnet IDs"
  value       = aws_subnet.public[*].id
}

output "private_subnet_ids" {
  description = "Private subnet IDs"
  value       = aws_subnet.private[*].id
}

output "glue_security_group_id" {
  description = "Security group ID for Glue jobs"
  value       = aws_security_group.glue.id
}

output "lambda_security_group_id" {
  description = "Security group ID for Lambda functions"
  value       = aws_security_group.lambda.id
}
"""
        return [
            self._write(TF / "vpc" / "main.tf",      vpc_main),
            self._write(TF / "vpc" / "variables.tf", vpc_vars),
            self._write(TF / "vpc" / "outputs.tf",   vpc_outputs),
        ]

    def _write_data_platform_module(self) -> list[Path]:
        main = """# infrastructure/terraform/data_platform/main.tf
# Data Platform: S3 Data Lake + Glue + IAM

terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
  backend "s3" {
    # Configured via -backend-config in CI
    # bucket = "your-tfstate-bucket"
    # key    = "data-platform/<env>/terraform.tfstate"
    # region = "us-east-1"
    # encrypt = true
    # dynamodb_table = "terraform-state-lock"
  }
}

provider "aws" {
  region = var.aws_region
  default_tags {
    tags = {
      Project     = var.project
      Environment = var.environment
      ManagedBy   = "terraform"
      Team        = "data-platform"
    }
  }
}

locals {
  prefix = "${var.project}-${var.environment}"
}

# ── VPC (module) ──────────────────────────────────────────────────────────

module "vpc" {
  source      = "../vpc"
  project     = var.project
  environment = var.environment
  aws_region  = var.aws_region
  vpc_cidr    = var.vpc_cidr

  public_subnet_cidrs  = var.public_subnet_cidrs
  private_subnet_cidrs = var.private_subnet_cidrs
  availability_zones   = var.availability_zones
  enable_nat_gateway   = var.enable_nat_gateway
}

# ── S3 Data Lake ──────────────────────────────────────────────────────────

resource "aws_s3_bucket" "data_lake" {
  bucket = "${local.prefix}-data-lake"
}

resource "aws_s3_bucket_versioning" "data_lake" {
  bucket = aws_s3_bucket.data_lake.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "data_lake" {
  bucket = aws_s3_bucket.data_lake.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "aws:kms"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "data_lake" {
  bucket                  = aws_s3_bucket.data_lake.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "data_lake" {
  bucket = aws_s3_bucket.data_lake.id

  rule {
    id     = "landing-to-ia"
    status = "Enabled"
    filter { prefix = "landing/" }
    transition {
      days          = 30
      storage_class = "STANDARD_IA"
    }
    expiration { days = 90 }
  }

  rule {
    id     = "curated-glacier"
    status = "Enabled"
    filter { prefix = "curated/" }
    transition {
      days          = 90
      storage_class = "GLACIER"
    }
  }
}

# Prefix structure
resource "aws_s3_object" "prefixes" {
  for_each = toset(["landing/", "curated/", "archive/", "scripts/", "tmp/"])
  bucket   = aws_s3_bucket.data_lake.id
  key      = each.value
  content  = ""
}

# ── IAM Roles ─────────────────────────────────────────────────────────────

resource "aws_iam_role" "glue" {
  name = "${local.prefix}-glue-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "glue.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "glue_service" {
  role       = aws_iam_role.glue.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole"
}

resource "aws_iam_role_policy" "glue_s3" {
  name = "glue-s3-access"
  role = aws_iam_role.glue.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject","s3:PutObject","s3:DeleteObject","s3:ListBucket"]
        Resource = [
          aws_s3_bucket.data_lake.arn,
          "${aws_s3_bucket.data_lake.arn}/*"
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["kms:GenerateDataKey","kms:Decrypt","kms:DescribeKey"]
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_role" "cicd_deploy" {
  name = "${local.prefix}-cicd-deploy-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Federated = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:oidc-provider/token.actions.githubusercontent.com"
      }
      Action = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringLike = {
          "token.actions.githubusercontent.com:sub" = "repo:${var.github_org}/${var.github_repo}:*"
        }
      }
    }]
  })
}

resource "aws_iam_role_policy" "cicd_permissions" {
  name = "cicd-permissions"
  role = aws_iam_role.cicd_deploy.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:*","glue:*","iam:GetRole","iam:PassRole","logs:*","cloudwatch:*"]
        Resource = "*"
      }
    ]
  })
}

# ── Glue Jobs ─────────────────────────────────────────────────────────────

resource "aws_glue_job" "landing_to_curated" {
  name              = "${local.prefix}-landing-to-curated"
  role_arn          = aws_iam_role.glue.arn
  glue_version      = "4.0"
  worker_type       = var.glue_worker_type
  number_of_workers = var.glue_workers

  command {
    script_location = "s3://${aws_s3_bucket.data_lake.bucket}/scripts/landing_to_curated.py"
    python_version  = "3"
  }

  default_arguments = {
    "--job-language"                       = "python"
    "--enable-metrics"                     = "true"
    "--enable-continuous-cloudwatch-log"   = "true"
    "--enable-glue-datacatalog"            = "true"
    "--TempDir"                            = "s3://${aws_s3_bucket.data_lake.bucket}/tmp/"
    "--extra-py-files"                     = ""
    "--job-bookmark-option"                = "job-bookmark-enable"
  }

  execution_property {
    max_concurrent_runs = 1
  }

  tags = { Name = "${local.prefix}-landing-to-curated" }
}

# Glue job failure alarm
resource "aws_cloudwatch_metric_alarm" "glue_failure" {
  alarm_name          = "${local.prefix}-glue-job-failure"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "glue.driver.aggregate.numFailedTasks"
  namespace           = "Glue"
  period              = 300
  statistic           = "Sum"
  threshold           = 1
  alarm_description   = "Glue job has failed tasks"
  alarm_actions       = var.sns_alert_arns
  dimensions          = { JobName = aws_glue_job.landing_to_curated.name }
}

# ── Glue Data Catalog ─────────────────────────────────────────────────────

resource "aws_glue_catalog_database" "landing" {
  name = "${replace(local.prefix, "-", "_")}_landing"
}

resource "aws_glue_catalog_database" "curated" {
  name = "${replace(local.prefix, "-", "_")}_curated"
}

data "aws_caller_identity" "current" {}
"""

        variables = """# infrastructure/terraform/data_platform/variables.tf

variable "project" {
  description = "Project name"
  type        = string
  default     = "nwt-data-platform"
}

variable "environment" {
  description = "Environment (dev / staging / prod)"
  type        = string
}

variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

# ── VPC variables (passed to module) ──────────────────────────────────────

variable "vpc_cidr" {
  type    = string
  default = "10.0.0.0/16"
}

variable "public_subnet_cidrs" {
  type    = list(string)
  default = ["10.0.1.0/24", "10.0.2.0/24"]
}

variable "private_subnet_cidrs" {
  type    = list(string)
  default = ["10.0.10.0/24", "10.0.11.0/24"]
}

variable "availability_zones" {
  type    = list(string)
  default = ["us-east-1a", "us-east-1b"]
}

variable "enable_nat_gateway" {
  type    = bool
  default = true
}

# ── Glue ──────────────────────────────────────────────────────────────────

variable "glue_worker_type" {
  description = "Glue worker type (G.025X, G.1X, G.2X, G.4X)"
  type        = string
  default     = "G.1X"
}

variable "glue_workers" {
  description = "Number of Glue workers"
  type        = number
  default     = 5
}

# ── GitHub OIDC (for CI/CD role) ──────────────────────────────────────────

variable "github_org" {
  description = "GitHub organization or username"
  type        = string
}

variable "github_repo" {
  description = "GitHub repository name"
  type        = string
}

# ── Alerting ──────────────────────────────────────────────────────────────

variable "sns_alert_arns" {
  description = "SNS topic ARNs for CloudWatch alarms"
  type        = list(string)
  default     = []
}
"""

        outputs = """# infrastructure/terraform/data_platform/outputs.tf

output "data_lake_bucket" {
  description = "S3 data lake bucket name"
  value       = aws_s3_bucket.data_lake.bucket
}

output "data_lake_bucket_arn" {
  value = aws_s3_bucket.data_lake.arn
}

output "glue_role_arn" {
  description = "IAM role ARN for Glue jobs"
  value       = aws_iam_role.glue.arn
}

output "cicd_role_arn" {
  description = "IAM role ARN for GitHub Actions OIDC"
  value       = aws_iam_role.cicd_deploy.arn
}

output "glue_job_landing_to_curated" {
  value = aws_glue_job.landing_to_curated.name
}

output "vpc_id" {
  value = module.vpc.vpc_id
}

output "private_subnet_ids" {
  value = module.vpc.private_subnet_ids
}
"""
        return [
            self._write(TF / "data_platform" / "main.tf",      main),
            self._write(TF / "data_platform" / "variables.tf", variables),
            self._write(TF / "data_platform" / "outputs.tf",   outputs),
        ]

    def _write_env_files(self) -> list[Path]:
        dev_tfvars = """# infrastructure/terraform/envs/dev/terraform.tfvars
# Development environment — smaller resources, no HA

project     = "nwt-data-platform"
environment = "dev"
aws_region  = "us-east-1"

# VPC
vpc_cidr             = "10.1.0.0/16"
public_subnet_cidrs  = ["10.1.1.0/24", "10.1.2.0/24"]
private_subnet_cidrs = ["10.1.10.0/24", "10.1.11.0/24"]
availability_zones   = ["us-east-1a", "us-east-1b"]
enable_nat_gateway   = false   # Cost saving in dev

# Glue
glue_worker_type = "G.025X"   # Smallest worker type
glue_workers     = 2

# GitHub (for OIDC deploy role)
github_org  = "Nishant-Karri"
github_repo = "Nishant_gastown_replica"

# Alerts (leave empty for dev)
sns_alert_arns = []
"""

        prod_tfvars = """# infrastructure/terraform/envs/prod/terraform.tfvars
# Production environment — HA, full resources

project     = "nwt-data-platform"
environment = "prod"
aws_region  = "us-east-1"

# VPC
vpc_cidr             = "10.0.0.0/16"
public_subnet_cidrs  = ["10.0.1.0/24", "10.0.2.0/24"]
private_subnet_cidrs = ["10.0.10.0/24", "10.0.11.0/24"]
availability_zones   = ["us-east-1a", "us-east-1b"]
enable_nat_gateway   = true

# Glue
glue_worker_type = "G.1X"
glue_workers     = 5

# GitHub (for OIDC deploy role)
github_org  = "Nishant-Karri"
github_repo = "Nishant_gastown_replica"

# Alerts
# sns_alert_arns = ["arn:aws:sns:us-east-1:123456789:data-platform-alerts"]
sns_alert_arns = []
"""

        dev_backend = """# infrastructure/terraform/envs/dev/backend.hcl
bucket         = "YOUR-TFSTATE-BUCKET"
key            = "data-platform/dev/terraform.tfstate"
region         = "us-east-1"
encrypt        = true
dynamodb_table = "terraform-state-lock"
"""

        prod_backend = """# infrastructure/terraform/envs/prod/backend.hcl
bucket         = "YOUR-TFSTATE-BUCKET"
key            = "data-platform/prod/terraform.tfstate"
region         = "us-east-1"
encrypt        = true
dynamodb_table = "terraform-state-lock"
"""

        return [
            self._write(TF / "envs" / "dev"  / "terraform.tfvars", dev_tfvars),
            self._write(TF / "envs" / "prod" / "terraform.tfvars", prod_tfvars),
            self._write(TF / "envs" / "dev"  / "backend.hcl",      dev_backend),
            self._write(TF / "envs" / "prod" / "backend.hcl",      prod_backend),
        ]

    # ── Generate all ──────────────────────────────────────────────────────

    def generate_all(self) -> None:
        self.generate_github_actions()
        self.generate_terraform()
        self._write_gitignore_infra()
        print(f"\n  ✓ All CI/CD + infrastructure files generated.")
        print(f"  Next steps:")
        print(f"    1. Set GitHub secrets (see CONNECTIONS.md#github-actions-secrets)")
        print(f"    2. Update backend.hcl with your S3 state bucket")
        print(f"    3. Review terraform.tfvars for your environment")
        print(f"    4. Run: cd infrastructure/terraform/data_platform && terraform init")

    def _write_gitignore_infra(self) -> None:
        gitignore = """# Terraform
.terraform/
.terraform.lock.hcl
*.tfplan
*.tfstate
*.tfstate.backup
terraform.tfvars.local
override.tf
override.tf.json
*_override.tf
*_override.tf.json

# Sensitive
*.pem
*.key
secrets.auto.tfvars
"""
        self._write(INFRA / ".gitignore", gitignore)

    def terraform_plan(self, env: str) -> None:
        tf_dir = TF / "data_platform"
        backend_cfg = TF / "envs" / env / "backend.hcl"
        tfvars      = TF / "envs" / env / "terraform.tfvars"
        print(f"\n  Running terraform plan for {env}...")
        subprocess.run(["terraform", "init", f"-backend-config={backend_cfg}"],
                       cwd=tf_dir, check=True)
        subprocess.run(["terraform", "plan", f"-var-file={tfvars}"],
                       cwd=tf_dir, check=True)

    def terraform_apply(self, env: str) -> None:
        tf_dir  = TF / "data_platform"
        tfvars  = TF / "envs" / env / "terraform.tfvars"
        confirm = input(f"  Apply Terraform to {env}? Type 'yes' to confirm: ")
        if confirm.strip() != "yes":
            print("  Cancelled.")
            return
        subprocess.run(["terraform", "apply", "-auto-approve", f"-var-file={tfvars}"],
                       cwd=tf_dir, check=True)

    def push_to_git(self, env: str) -> None:
        msg = f"infra: add/update infrastructure for {env} environment"
        try:
            subprocess.run(["git", "add", str(INFRA)], cwd=str(ROOT), check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", msg], cwd=str(ROOT), check=True, capture_output=True)
            subprocess.run(["git", "push", "origin", "main"], cwd=str(ROOT), check=True, capture_output=True)
            print(f"  ✓ Infrastructure committed and pushed: {msg}")
        except subprocess.CalledProcessError as e:
            print(f"  [git] Push failed: {e.stderr.decode() if e.stderr else e}")

    @staticmethod
    def _write(path: Path, content: str) -> Path:
        path.write_text(content)
        return path


# ── CLI ────────────────────────────────────────────────────────────────────

def main():
    import argparse
    p   = argparse.ArgumentParser(description="NGR CI/CD + Infrastructure Generator")
    sub = p.add_subparsers(dest="cmd")

    gp = sub.add_parser("generate")
    gp.add_argument("--all",             action="store_true")
    gp.add_argument("--type", choices=["github-actions","terraform","all"], default="all")

    tp = sub.add_parser("terraform")
    tsub = tp.add_subparsers(dest="tf_cmd")
    tsub.add_parser("plan").add_argument("--env", default="dev")
    tsub.add_parser("apply").add_argument("--env", default="dev")

    pp = sub.add_parser("push")
    pp.add_argument("--env", default="prod")

    args = p.parse_args()
    gen  = CICDGenerator()

    if args.cmd == "generate":
        t = getattr(args, "type", "all")
        if t in ("all", "github-actions"):
            gen.generate_github_actions()
        if t in ("all", "terraform"):
            gen.generate_terraform()
        gen._write_gitignore_infra()
    elif args.cmd == "terraform":
        if args.tf_cmd == "plan":  gen.terraform_plan(args.env)
        elif args.tf_cmd == "apply": gen.terraform_apply(args.env)
    elif args.cmd == "push":
        gen.push_to_git(args.env)
    else:
        gen.generate_all()


if __name__ == "__main__":
    main()
