resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = {
    Name = "${local.name_prefix}-vpc"
  }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name = "${local.name_prefix}-igw"
  }
}

resource "aws_subnet" "public" {
  for_each = local.public_subnets

  vpc_id                  = aws_vpc.main.id
  availability_zone       = each.value.availability_zone
  cidr_block              = each.value.cidr_block
  map_public_ip_on_launch = true

  tags = {
    Name = "${local.name_prefix}-public-${each.key}"
    Tier = "public"
  }
}

resource "aws_subnet" "private" {
  for_each = local.private_subnets

  vpc_id                  = aws_vpc.main.id
  availability_zone       = each.value.availability_zone
  cidr_block              = each.value.cidr_block
  map_public_ip_on_launch = false

  tags = {
    Name = "${local.name_prefix}-private-${each.key}"
    Tier = "private"
  }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name = "${local.name_prefix}-public-rt"
  }
}

resource "aws_route" "public_internet" {
  route_table_id         = aws_route_table.public.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.main.id
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name = "${local.name_prefix}-private-rt"
  }
}

resource "aws_route_table_association" "public" {
  for_each = aws_subnet.public

  subnet_id      = each.value.id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table_association" "private" {
  for_each = aws_subnet.private

  subnet_id      = each.value.id
  route_table_id = aws_route_table.private.id
}

resource "aws_security_group" "alb" {
  name_prefix = "${local.name_prefix}-alb-"
  description = "Controls traffic for the Product Application Load Balancer"
  vpc_id      = aws_vpc.main.id

  tags = {
    Name = "${local.name_prefix}-alb-sg"
  }
}

resource "aws_security_group" "product" {
  name_prefix = "${local.name_prefix}-product-"
  description = "Controls traffic for Product Service instances"
  vpc_id      = aws_vpc.main.id

  tags = {
    Name = "${local.name_prefix}-product-sg"
  }
}

resource "aws_security_group" "coupon" {
  name_prefix = "${local.name_prefix}-coupon-"
  description = "Controls traffic for the Coupon Service instance"
  vpc_id      = aws_vpc.main.id

  tags = {
    Name = "${local.name_prefix}-coupon-sg"
  }
}

resource "aws_security_group" "database" {
  name_prefix = "${local.name_prefix}-database-"
  description = "Controls traffic for the private MySQL database"
  vpc_id      = aws_vpc.main.id

  tags = {
    Name = "${local.name_prefix}-database-sg"
  }
}

resource "aws_vpc_security_group_ingress_rule" "alb_http" {
  for_each = var.allowed_client_cidrs

  security_group_id = aws_security_group.alb.id
  description       = "HTTP from approved client ${each.value}"
  cidr_ipv4         = each.value
  from_port         = 80
  to_port           = 80
  ip_protocol       = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "alb_to_product" {
  security_group_id            = aws_security_group.alb.id
  description                  = "Product traffic"
  referenced_security_group_id = aws_security_group.product.id
  from_port                    = 9090
  to_port                      = 9090
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_ingress_rule" "product_from_alb" {
  security_group_id            = aws_security_group.product.id
  description                  = "Product traffic from the ALB"
  referenced_security_group_id = aws_security_group.alb.id
  from_port                    = 9090
  to_port                      = 9090
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "product_all_ipv4" {
  security_group_id = aws_security_group.product.id
  description       = "All IPv4 outbound traffic for the lab"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}

resource "aws_vpc_security_group_ingress_rule" "coupon_from_product" {
  security_group_id            = aws_security_group.coupon.id
  description                  = "Coupon traffic from Product instances"
  referenced_security_group_id = aws_security_group.product.id
  from_port                    = 9091
  to_port                      = 9091
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "coupon_all_ipv4" {
  security_group_id = aws_security_group.coupon.id
  description       = "All IPv4 outbound traffic for the lab"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}

resource "aws_vpc_security_group_ingress_rule" "database_from_product" {
  security_group_id            = aws_security_group.database.id
  description                  = "MySQL from Product instances"
  referenced_security_group_id = aws_security_group.product.id
  from_port                    = 3306
  to_port                      = 3306
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_ingress_rule" "database_from_coupon" {
  security_group_id            = aws_security_group.database.id
  description                  = "MySQL from the Coupon instance"
  referenced_security_group_id = aws_security_group.coupon.id
  from_port                    = 3306
  to_port                      = 3306
  ip_protocol                  = "tcp"
}
