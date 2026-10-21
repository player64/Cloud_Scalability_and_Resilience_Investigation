provider "aws" {
  region              = var.aws_region
  allowed_account_ids = [var.expected_account_id]

  default_tags {
    tags = {
      Project   = var.project_name
      ManagedBy = "Terraform"
    }
  }
}

locals {
  name_prefix = var.project_name

  public_subnets = {
    a = {
      availability_zone = var.availability_zones[0]
      cidr_block        = var.public_subnet_cidrs[0]
    }
    b = {
      availability_zone = var.availability_zones[1]
      cidr_block        = var.public_subnet_cidrs[1]
    }
  }

  private_subnets = {
    a = {
      availability_zone = var.availability_zones[0]
      cidr_block        = var.private_subnet_cidrs[0]
    }
    b = {
      availability_zone = var.availability_zones[1]
      cidr_block        = var.private_subnet_cidrs[1]
    }
  }
}
