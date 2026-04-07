# infrastructure/terraform/envs/dev/terraform.tfvars
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
github_repo = "Multi_Digital_Workers"

# Alerts (leave empty for dev)
sns_alert_arns = []
