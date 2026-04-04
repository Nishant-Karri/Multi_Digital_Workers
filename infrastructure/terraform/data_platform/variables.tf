# infrastructure/terraform/data_platform/variables.tf

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
