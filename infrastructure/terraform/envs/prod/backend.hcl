# infrastructure/terraform/envs/prod/backend.hcl
bucket         = "YOUR-TFSTATE-BUCKET"
key            = "data-platform/prod/terraform.tfstate"
region         = "us-east-1"
encrypt        = true
dynamodb_table = "terraform-state-lock"
