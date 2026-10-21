resource "aws_lb" "product" {
  name_prefix        = "prod-"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = [for subnet in aws_subnet.public : subnet.id]

  depends_on = [
    aws_route.public_internet,
    aws_route_table_association.public,
    aws_vpc_security_group_ingress_rule.alb_http,
    aws_vpc_security_group_egress_rule.alb_to_product,
  ]

  tags = {
    Name = "${local.name_prefix}-product-alb"
  }
}

resource "aws_lb_target_group" "product" {
  name_prefix = "prod-"
  target_type = "instance"
  protocol    = "HTTP"
  port        = 9090
  vpc_id      = aws_vpc.main.id

  load_balancing_algorithm_type = "round_robin"

  stickiness {
    type    = "lb_cookie"
    enabled = false
  }

  health_check {
    enabled             = true
    protocol            = "HTTP"
    path                = "/actuator/health/readiness"
    port                = "9090"
    matcher             = "200"
    interval            = 15
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 2
  }

  tags = {
    Name = "${local.name_prefix}-product"
  }
}

resource "aws_lb_listener" "product_http" {
  load_balancer_arn = aws_lb.product.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.product.arn
  }
}

resource "aws_launch_template" "product" {
  name_prefix = "${local.name_prefix}-product-"
  # Reuse the existing owner/platform-verified, pinned AL2023 AMI.
  image_id      = data.aws_ami.coupon.id
  instance_type = var.product_instance_type

  iam_instance_profile {
    name = aws_iam_instance_profile.product.name
  }

  metadata_options {
    http_endpoint = "enabled"
    http_tokens   = "required"
  }

  monitoring {
    enabled = true
  }

  network_interfaces {
    device_index                = 0
    associate_public_ip_address = true
    delete_on_termination       = true
    security_groups             = [aws_security_group.product.id]
    # ASG selects the subnet; do not also set top-level security groups.
  }

  block_device_mappings {
    device_name = data.aws_ami.coupon.root_device_name

    ebs {
      encrypted             = true
      delete_on_termination = true
      volume_type           = "gp3"
      volume_size           = 12
    }
  }

  user_data = base64encode(templatefile("${path.module}/templates/product-user-data.sh.tftpl", {
    region     = var.aws_region
    bucket     = aws_s3_bucket.artifacts.id
    jar_key    = aws_s3_object.product_jar.key
    jar_sha256 = local.product_jar_sha256
    log_group  = aws_cloudwatch_log_group.applications.name
    runtime    = file("${path.module}/scripts/product-runtime.py")
    configuration = jsonencode({
      region        = var.aws_region
      host          = aws_db_instance.main.address
      port          = aws_db_instance.main.port
      database      = aws_db_instance.main.db_name
      app_parameter = aws_ssm_parameter.db_app_password.name
      coupon_url    = "http://${aws_instance.coupon.private_ip}:9091"
    })
  }))

  tag_specifications {
    resource_type = "instance"
    tags = {
      Name      = "${local.name_prefix}-product"
      Project   = var.project_name
      ManagedBy = "Terraform"
    }
  }

  tags = {
    Name = "${local.name_prefix}-product"
  }
}

resource "aws_autoscaling_group" "product" {
  name_prefix         = "${local.name_prefix}-product-"
  min_size            = 1
  desired_capacity    = 1
  max_size            = 1
  vpc_zone_identifier = [for subnet in aws_subnet.public : subnet.id]
  target_group_arns   = [aws_lb_target_group.product.arn]

  health_check_type         = "ELB"
  health_check_grace_period = 600
  default_instance_warmup   = 300
  # Keep Launch/Terminate/HealthCheck/ReplaceUnhealthy enabled.
  suspended_processes = []

  launch_template {
    id      = aws_launch_template.product.id
    version = aws_launch_template.product.latest_version
  }

  # Template/build/Coupon-IP changes roll existing members between experiments.
  # Baseline max=1 accepts maintenance interruption without extra capacity.
  instance_refresh {
    strategy = "Rolling"
    preferences {
      min_healthy_percentage = 0
      max_healthy_percentage = 100
      instance_warmup        = 300
      skip_matching          = true
    }
  }

  depends_on = [
    aws_lb_listener.product_http,
    aws_route.public_internet,
    aws_route_table_association.public,
    aws_vpc_security_group_ingress_rule.product_from_alb,
    aws_vpc_security_group_egress_rule.product_all_ipv4,
    aws_vpc_security_group_ingress_rule.coupon_from_product,
    aws_vpc_security_group_ingress_rule.database_from_product,
    aws_iam_role_policy.product_runtime,
    aws_iam_role_policy_attachment.product_ssm_core,
    aws_iam_role_policy_attachment.product_cloudwatch_agent,
    aws_s3_object.product_jar,
    aws_cloudwatch_log_group.applications,
  ]

  tag {
    key                 = "Name"
    value               = "${local.name_prefix}-product"
    propagate_at_launch = true
  }
}
