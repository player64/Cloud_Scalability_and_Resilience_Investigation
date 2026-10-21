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

<<<<<<< ours
=======
variable "expected_account_id" {
  description = "Twelve-digit AWS account ID allowed by the provider."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^[0-9]{12}$", var.expected_account_id))
    error_message = "expected_account_id must contain exactly 12 digits."
  }
}

>>>>>>> theirs
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
