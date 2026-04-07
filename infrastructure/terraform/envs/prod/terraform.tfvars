# infrastructure/terraform/envs/prod/terraform.tfvars
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
github_repo = "Multi_Digital_Workers"

# Alerts
# sns_alert_arns = ["arn:aws:sns:us-east-1:123456789:data-platform-alerts"]
sns_alert_arns = []
