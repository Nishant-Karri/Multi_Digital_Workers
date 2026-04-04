# infrastructure/terraform/envs/dev/backend.hcl
bucket         = "YOUR-TFSTATE-BUCKET"
key            = "data-platform/dev/terraform.tfstate"
region         = "us-east-1"
encrypt        = true
dynamodb_table = "terraform-state-lock"
