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
