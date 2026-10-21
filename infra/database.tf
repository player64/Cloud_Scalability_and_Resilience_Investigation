resource "aws_db_subnet_group" "main" {
  name       = "${local.name_prefix}-database-subnets"
  subnet_ids = [for subnet in aws_subnet.private : subnet.id]

  tags = {
    Name = "${local.name_prefix}-database-subnets"
  }
}

resource "aws_db_instance" "main" {
  identifier = "${local.name_prefix}-mysql"

  engine                     = "mysql"
  engine_version             = "8.4.11"
  auto_minor_version_upgrade = false
  instance_class             = var.db_instance_class

  allocated_storage = 20
  storage_type      = "gp3"
  storage_encrypted = true

  db_name  = "servicedb"
  username = "ca1admin"
  password = var.db_admin_password
  port     = 3306

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.database.id]
  publicly_accessible    = false
  multi_az               = false

  backup_retention_period = 0
  skip_final_snapshot     = true
  deletion_protection     = false

  monitoring_interval          = 0
  performance_insights_enabled = false

  depends_on = [
    aws_route_table_association.private,
    aws_vpc_security_group_ingress_rule.database_from_coupon,
    aws_vpc_security_group_ingress_rule.database_from_product,
  ]

  tags = {
    Name = "${local.name_prefix}-mysql"
  }
}
