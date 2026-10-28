output "vpc_id" {
  description = "ID of the assignment VPC."
  value       = aws_vpc.main.id
}

output "public_subnet_ids" {
  description = "Public subnet IDs keyed by Availability Zone slot."
  value       = { for key, subnet in aws_subnet.public : key => subnet.id }
}

output "private_subnet_ids" {
  description = "Private database subnet IDs keyed by Availability Zone slot."
  value       = { for key, subnet in aws_subnet.private : key => subnet.id }
}

output "alb_security_group_id" {
  description = "Security group ID reserved for the future Application Load Balancer."
  value       = aws_security_group.alb.id
}

output "product_security_group_id" {
  description = "Security group ID for future Product Service instances."
  value       = aws_security_group.product.id
}

output "coupon_security_group_id" {
  description = "Security group ID for the future Coupon Service instance."
  value       = aws_security_group.coupon.id
}

output "database_security_group_id" {
  description = "Security group ID for the future private database."
  value       = aws_security_group.database.id
}

output "rds_identifier" {
  description = "Identifier of the RDS MySQL instance."
  value       = aws_db_instance.main.identifier
}

output "rds_address" {
  description = "Hostname of the RDS MySQL instance."
  value       = aws_db_instance.main.address
}

output "rds_port" {
  description = "Port of the RDS MySQL instance."
  value       = aws_db_instance.main.port
}

output "artifact_bucket" {
  description = "Name of the private S3 bucket containing application JARs."
  value       = aws_s3_bucket.artifacts.id
}

output "evidence_bucket" {
  description = "Disposable S3 bucket for load-test evidence; destroy empties it."
  value       = aws_s3_bucket.evidence.id
}

output "aws_region" {
  description = "Region for the student-operated evidence sync."
  value       = var.aws_region
}

output "load_generator_public_ip" {
  description = "Public IPv4 address for SSH and SCP to the load generator."
  value       = aws_instance.load_generator.public_ip
}

output "load_generator_ami_id" {
  description = "Pinned Ubuntu AMI used by the load generator."
  value       = data.aws_ami.load_generator.id
}

output "product_jar_key" {
  description = "Immutable S3 object key for the Product Service JAR."
  value       = aws_s3_object.product_jar.key
}

output "product_jar_sha256" {
  description = "SHA-256 checksum of the Product Service JAR."
  value       = local.product_jar_sha256
}

output "coupon_jar_key" {
  description = "Immutable S3 object key for the Coupon Service JAR."
  value       = aws_s3_object.coupon_jar.key
}

output "coupon_jar_sha256" {
  description = "SHA-256 checksum of the Coupon Service JAR."
  value       = local.coupon_jar_sha256
}

output "product_iam_role_name" {
  description = "Name of the Product Service EC2 IAM role."
  value       = aws_iam_role.product.name
}

output "product_instance_profile_name" {
  description = "Name of the Product Service EC2 instance profile."
  value       = aws_iam_instance_profile.product.name
}

output "coupon_iam_role_name" {
  description = "Name of the Coupon Service EC2 IAM role."
  value       = aws_iam_role.coupon.name
}

output "coupon_instance_profile_name" {
  description = "Name of the Coupon Service EC2 instance profile."
  value       = aws_iam_instance_profile.coupon.name
}

output "application_log_group_name" {
  description = "CloudWatch log group for Product and Coupon application logs."
  value       = aws_cloudwatch_log_group.applications.name
}

output "coupon_instance_id" {
  description = "Coupon EC2 ID for Session Manager."
  value       = aws_instance.coupon.id
}

output "coupon_private_ip" {
  description = "Coupon private address; keep the instance unchanged during experiments."
  value       = aws_instance.coupon.private_ip
}

output "alb_url" {
  description = "Product HTTP URL, reachable from the approved client CIDRs."
  value       = "http://${aws_lb.product.dns_name}"
}

output "target_group_arn" {
  description = "Product target group ARN for health verification."
  value       = aws_lb_target_group.product.arn
}

output "product_asg_name" {
  description = "Name of the baseline Product Auto Scaling Group."
  value       = aws_autoscaling_group.product.name
}

output "experiment_profile" {
  description = "Experiment profile selected for this Terraform deployment."
  value       = var.experiment_profile
}

output "product_launch_template_id" {
  description = "ID of the Product Launch Template."
  value       = aws_launch_template.product.id
}

output "product_launch_template_version" {
  description = "Numeric Product Launch Template version used by the ASG."
  value       = aws_launch_template.product.latest_version
}
