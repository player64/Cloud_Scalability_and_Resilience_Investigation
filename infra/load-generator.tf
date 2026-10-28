data "aws_vpc" "default" {
  default = true
}

data "aws_subnet" "load_generator" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }

  filter {
    name   = "availability-zone"
    values = [var.availability_zones[0]]
  }

  filter {
    name   = "default-for-az"
    values = ["true"]
  }
}

data "aws_ami" "load_generator" {
  owners = ["099720109477"] # Canonical

  filter {
    name   = "image-id"
    values = [var.load_generator_ami_id]
  }

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd*/ubuntu-noble-24.04-amd64-server-*"]
  }

  filter {
    name   = "architecture"
    values = ["x86_64"]
  }
}

resource "aws_security_group" "load_generator" {
  name_prefix = "${local.name_prefix}-load-generator-"
  description = "SSH and outbound traffic for the disposable load generator"
  vpc_id      = data.aws_vpc.default.id

  tags = {
    Name = "${local.name_prefix}-load-generator-sg"
  }
}

resource "aws_vpc_security_group_ingress_rule" "load_generator_ssh" {
  for_each = var.allowed_client_cidrs

  security_group_id = aws_security_group.load_generator.id
  description       = "SSH from approved client ${each.value}"
  cidr_ipv4         = each.value
  from_port         = 22
  to_port           = 22
  ip_protocol       = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "load_generator_http" {
  security_group_id = aws_security_group.load_generator.id
  description       = "HTTP to the Product ALB and package mirrors"
  cidr_ipv4         = "0.0.0.0/0"
  from_port         = 80
  to_port           = 80
  ip_protocol       = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "load_generator_https" {
  security_group_id = aws_security_group.load_generator.id
  description       = "HTTPS for S3, AWS APIs and package installation"
  cidr_ipv4         = "0.0.0.0/0"
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
}

resource "aws_iam_role" "load_generator" {
  name_prefix        = "${local.name_prefix}-load-generator-"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume_role.json
}

resource "aws_iam_instance_profile" "load_generator" {
  name_prefix = "${local.name_prefix}-load-generator-"
  role        = aws_iam_role.load_generator.name
}

data "aws_iam_policy_document" "load_generator" {
  statement {
    sid       = "ReadTestFramework"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = [for object in aws_s3_object.load_tests : object.arn]
  }

  statement {
    sid       = "ListTestFramework"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.artifacts.arn]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["load-tests/*"]
    }
  }

  statement {
    sid       = "UploadEvidence"
    effect    = "Allow"
    actions   = ["s3:PutObject", "s3:AbortMultipartUpload"]
    resources = ["${aws_s3_bucket.evidence.arn}/evidence/*"]
  }

  statement {
    sid    = "ReadExperimentState"
    effect = "Allow"
    actions = [
      "autoscaling:DescribeAutoScalingGroups",
      "autoscaling:DescribePolicies",
      "autoscaling:DescribeScalingActivities",
      "elasticloadbalancing:DescribeTargetGroups",
      "elasticloadbalancing:DescribeTargetHealth",
      "cloudwatch:DescribeAlarms",
      "cloudwatch:GetMetricData",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "load_generator" {
  name_prefix = "${local.name_prefix}-load-generator-"
  role        = aws_iam_role.load_generator.id
  policy      = data.aws_iam_policy_document.load_generator.json
}

resource "aws_instance" "load_generator" {
  ami                         = data.aws_ami.load_generator.id
  instance_type               = var.load_generator_instance_type
  subnet_id                   = data.aws_subnet.load_generator.id
  associate_public_ip_address = true
  vpc_security_group_ids      = [aws_security_group.load_generator.id]
  iam_instance_profile        = aws_iam_instance_profile.load_generator.name
  key_name                    = "mj256"

  metadata_options {
    http_endpoint = "enabled"
    http_tokens   = "required"
  }

  root_block_device {
    encrypted             = true
    delete_on_termination = true
    volume_type           = "gp3"
    volume_size           = 16
  }

  user_data = templatefile("${path.module}/templates/load-generator-user-data.sh.tftpl", {
    region = var.aws_region
    bucket = aws_s3_bucket.artifacts.id
  })

  depends_on = [
    aws_s3_object.load_tests,
    aws_iam_role_policy.load_generator,
    aws_vpc_security_group_ingress_rule.load_generator_ssh,
    aws_vpc_security_group_egress_rule.load_generator_http,
    aws_vpc_security_group_egress_rule.load_generator_https,
  ]

  tags = {
    Name = "${local.name_prefix}-load-generator"
  }
}

# The generator is in the default VPC, so its public address reaches this ALB.
resource "aws_vpc_security_group_ingress_rule" "alb_from_load_generator" {
  security_group_id = aws_security_group.alb.id
  description       = "HTTP from the disposable load generator"
  cidr_ipv4         = "${aws_instance.load_generator.public_ip}/32"
  from_port         = 80
  to_port           = 80
  ip_protocol       = "tcp"
}
