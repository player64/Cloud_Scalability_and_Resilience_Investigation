variable "project_name" {
  description = "Name prefix and Project tag for the assignment resources."
  type        = string
  default     = "ca1"

  validation {
    condition     = length(trimspace(var.project_name)) > 0
    error_message = "project_name must not be empty."
  }
}

variable "aws_region" {
  description = "AWS region in which the infrastructure will be created."
  type        = string
  nullable    = false
}

variable "availability_zones" {
  description = "Two distinct Availability Zones in aws_region."
  type        = list(string)
  nullable    = false

  validation {
    condition     = length(var.availability_zones) == 2 && length(distinct(var.availability_zones)) == 2
    error_message = "availability_zones must contain exactly two distinct values."
  }
}

variable "vpc_cidr" {
  description = "IPv4 CIDR block for the VPC."
  type        = string
  default     = "10.42.0.0/16"

  validation {
    condition     = can(cidrnetmask(var.vpc_cidr))
    error_message = "vpc_cidr must be a valid IPv4 CIDR block."
  }
}

variable "public_subnet_cidrs" {
  description = "IPv4 CIDR blocks for the public subnets, ordered to match availability_zones."
  type        = list(string)
  default     = ["10.42.1.0/24", "10.42.2.0/24"]

  validation {
    condition     = length(var.public_subnet_cidrs) == 2 && alltrue([for cidr in var.public_subnet_cidrs : can(cidrnetmask(cidr))])
    error_message = "public_subnet_cidrs must contain exactly two valid IPv4 CIDR blocks."
  }
}

variable "private_subnet_cidrs" {
  description = "IPv4 CIDR blocks for the private database subnets, ordered to match availability_zones."
  type        = list(string)
  default     = ["10.42.11.0/24", "10.42.12.0/24"]

  validation {
    condition     = length(var.private_subnet_cidrs) == 2 && alltrue([for cidr in var.private_subnet_cidrs : can(cidrnetmask(cidr))])
    error_message = "private_subnet_cidrs must contain exactly two valid IPv4 CIDR blocks."
  }
}

variable "allowed_client_cidrs" {
  description = "Approved public IPv4 CIDR blocks allowed to reach the future ALB on TCP port 80."
  type        = set(string)
  nullable    = false

  validation {
    condition     = length(var.allowed_client_cidrs) > 0 && alltrue([for cidr in var.allowed_client_cidrs : can(cidrnetmask(cidr))])
    error_message = "allowed_client_cidrs must contain at least one valid IPv4 CIDR block."
  }

  validation {
    condition     = !contains(var.allowed_client_cidrs, "0.0.0.0/0")
    error_message = "allowed_client_cidrs must not permit all IPv4 addresses."
  }
}

variable "db_instance_class" {
  description = "RDS instance class approved for MySQL in the selected region."
  type        = string
  nullable    = false

  validation {
    condition     = startswith(var.db_instance_class, "db.")
    error_message = "db_instance_class must be an RDS class name beginning with db."
  }
}

variable "db_name" {
  description = "Database name for the RDS MySQL instance"
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^[a-zA-Z0-9]+$", var.db_name))
    error_message = "Database name must contain only letters and numbers."
  }
}

variable "db_user" {
  description = "RDS MySQL master username"
  type        = string
  sensitive   = true
  nullable    = false

  validation {
    condition = can(regex("^[a-zA-Z][a-zA-Z0-9]{0,15}$", var.db_user))
    error_message = "Username must start with a letter, contain only alphanumeric characters, and be 1–16 characters long."
  }

  validation {
    condition     = !contains(["root"], lower(var.db_user))
    error_message = "Username cannot be a reserved MySQL username."
  }
}

variable "db_admin_password" {
  description = "Administrator password for the RDS MySQL instance. Supply it through a protected input mechanism."
  type        = string
  sensitive   = true
  nullable    = false

  validation {
    condition     = length(var.db_admin_password) >= 8 && length(var.db_admin_password) <= 41
    error_message = "db_admin_password must be between 8 and 41 characters."
  }

  validation {
    condition     = length(regexall("[/@\" ]", var.db_admin_password)) == 0
    error_message = "db_admin_password must not contain a slash, double quote, at sign or space."
  }
}

variable "db_app_password" {
  description = "Password for the application database user. Supply it through a protected input mechanism."
  type        = string
  sensitive   = true
  nullable    = false

  validation {
    condition     = length(var.db_app_password) >= 8
    error_message = "db_app_password must contain at least 8 characters."
  }
}

variable "product_jar_path" {
  description = "Path to the approved, existing Product Service JAR."
  type        = string
  nullable    = false

  validation {
    condition     = length(trimspace(var.product_jar_path)) > 0
    error_message = "product_jar_path must not be empty."
  }
}

variable "coupon_jar_path" {
  description = "Path to the approved, existing Coupon Service JAR."
  type        = string
  nullable    = false

  validation {
    condition     = length(trimspace(var.coupon_jar_path)) > 0
    error_message = "coupon_jar_path must not be empty."
  }
}

variable "product_build_id" {
  description = "Version-specific identifier for the Product Service build."
  type        = string
  default     = "0.0.1-SNAPSHOT"

  validation {
    condition     = can(regex("^[0-9A-Za-z._-]+$", var.product_build_id))
    error_message = "product_build_id may contain only letters, digits, dots, underscores and hyphens."
  }
}

variable "coupon_build_id" {
  description = "Version-specific identifier for the Coupon Service build."
  type        = string
  default     = "0.0.1-SNAPSHOT"

  validation {
    condition     = can(regex("^[0-9A-Za-z._-]+$", var.coupon_build_id))
    error_message = "coupon_build_id may contain only letters, digits, dots, underscores and hyphens."
  }
}

variable "coupon_ami_id" {
  description = "Pinned official Amazon Linux 2023 standard x86_64 AMI ID in aws_region; verify availability before deployment."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^ami-[0-9a-f]{17}$", var.coupon_ami_id))
    error_message = "coupon_ami_id must be a literal AMI ID, not a moving latest-image reference."
  }
}

variable "coupon_instance_type" {
  description = "Approved x86_64 EC2 type for the fixed Coupon host."
  type        = string
  default     = "t3.micro"
  nullable    = false
}

variable "product_instance_type" {
  description = "Approved x86_64 EC2 type for Product instances; keep fixed across experiments."
  type        = string
  default     = "t3.micro"
  nullable    = false
}

variable "product_min" {
  description = "Minimum Product ASG capacity."
  type        = number
  default     = 1
  nullable    = false

  validation {
    condition     = var.product_min == floor(var.product_min) && var.product_min >= 1 && var.product_min <= 2
    error_message = "product_min must be an integer between 1 and 2."
  }
}

variable "product_desired" {
  description = "Terraform-managed desired Product capacity; do not apply during measurements."
  type        = number
  default     = 1
  nullable    = false

  validation {
    condition     = var.product_desired == floor(var.product_desired) && var.product_desired >= 1 && var.product_desired <= 2
    error_message = "product_desired must be an integer between 1 and 2."
  }

  validation {
    condition     = var.product_min <= var.product_desired && var.product_desired <= var.product_max
    error_message = "Product capacities must satisfy min <= desired <= max."
  }
}

variable "product_max" {
  description = "Maximum Product ASG capacity."
  type        = number
  default     = 1
  nullable    = false

  validation {
    condition     = var.product_max == floor(var.product_max) && var.product_max >= 1 && var.product_max <= 2
    error_message = "product_max must be an integer between 1 and 2."
  }
}

variable "enable_product_scaling" {
  description = "Enable CPU target tracking only for the elasticity experiment."
  type        = bool
  default     = false
  nullable    = false

  validation {
    condition     = !var.enable_product_scaling || (var.product_min == 1 && var.product_desired == 1 && var.product_max == 2)
    error_message = "Elasticity requires Product min=1, desired=1, max=2."
  }
}

variable "product_cpu_target" {
  description = "Target average Product ASG CPU utilisation percentage for elasticity."
  type        = number
  default     = 50
  nullable    = false

  validation {
    condition     = var.product_cpu_target > 0 && var.product_cpu_target <= 100
    error_message = "product_cpu_target must be greater than 0 and at most 100."
  }
}

variable "product_startup_timeout_seconds" {
  description = "Product systemd startup deadline; pre-start receives five seconds less. Preserve the existing dependency retry budget."
  type        = number
  default     = 185
  nullable    = false

  validation {
    condition     = var.product_startup_timeout_seconds == floor(var.product_startup_timeout_seconds) && var.product_startup_timeout_seconds >= 185
    error_message = "product_startup_timeout_seconds must be an integer of at least 185."
  }
}

variable "product_health_check_grace_seconds" {
  description = "ASG ELB health-check grace period in seconds."
  type        = number
  default     = 600
  nullable    = false

  validation {
    condition     = var.product_health_check_grace_seconds == floor(var.product_health_check_grace_seconds) && var.product_health_check_grace_seconds >= 0
    error_message = "product_health_check_grace_seconds must be a non-negative integer."
  }
}

variable "product_instance_warmup_seconds" {
  description = "Default ASG and rolling refresh warmup in seconds; target tracking inherits this value."
  type        = number
  default     = 300
  nullable    = false

  validation {
    condition     = var.product_instance_warmup_seconds == floor(var.product_instance_warmup_seconds) && var.product_instance_warmup_seconds >= 0
    error_message = "product_instance_warmup_seconds must be a non-negative integer."
  }
}
