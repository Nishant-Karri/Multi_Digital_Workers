# infrastructure/terraform/data_platform/main.tf
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
