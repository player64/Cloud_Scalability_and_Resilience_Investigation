# The operator pins a regional AMI; this lookup verifies its owner and platform.
data "aws_ami" "coupon" {
  owners = ["amazon"]

  filter {
    name   = "image-id"
    values = [var.coupon_ami_id]
  }
  filter {
    name   = "name"
    values = ["al2023-ami-2023.*-x86_64"]
  }
  filter {
    name   = "architecture"
    values = ["x86_64"]
  }
}

resource "aws_instance" "coupon" {
  ami                         = data.aws_ami.coupon.id
  instance_type               = var.coupon_instance_type
  subnet_id                   = aws_subnet.public["a"].id
  associate_public_ip_address = true
  vpc_security_group_ids      = [aws_security_group.coupon.id]
  iam_instance_profile        = aws_iam_instance_profile.coupon.name

  metadata_options {
    http_endpoint = "enabled"
    http_tokens   = "required"
  }

  root_block_device {
    encrypted             = true
    delete_on_termination = true
    volume_type           = "gp3"
    volume_size           = 12
  }

  user_data_replace_on_change = true
  user_data = templatefile("${path.module}/templates/coupon-user-data.sh.tftpl", {
    region     = var.aws_region
    bucket     = aws_s3_bucket.artifacts.id
    jar_key    = aws_s3_object.coupon_jar.key
    jar_sha256 = local.coupon_jar_sha256
    log_group  = aws_cloudwatch_log_group.applications.name
    runtime    = file("${path.module}/scripts/coupon-operator.py")
    sql        = file("${path.module}/sql/initialise.sql")
    configuration = jsonencode({
      region          = var.aws_region
      host            = aws_db_instance.main.address
      port            = aws_db_instance.main.port
      database        = aws_db_instance.main.db_name
      admin_user      = aws_db_instance.main.username
      admin_parameter = aws_ssm_parameter.db_admin_password.name
      app_parameter   = aws_ssm_parameter.db_app_password.name
    })
  })

  depends_on = [
    aws_route.public_internet,
    aws_route_table_association.public,
    aws_vpc_security_group_egress_rule.coupon_all_ipv4,
    aws_vpc_security_group_ingress_rule.coupon_from_product,
    aws_vpc_security_group_ingress_rule.database_from_coupon,
    aws_iam_role_policy.coupon_runtime,
    aws_iam_role_policy_attachment.coupon_ssm_core,
    aws_iam_role_policy_attachment.coupon_cloudwatch_agent,
  ]

  tags = {
    Name = "${local.name_prefix}-coupon"
  }
}
