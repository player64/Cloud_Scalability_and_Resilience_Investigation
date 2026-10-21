locals {
  product_jar_sha256 = filesha256(var.product_jar_path)
  coupon_jar_sha256  = filesha256(var.coupon_jar_path)

  product_jar_key = "product/${var.product_build_id}-${local.product_jar_sha256}/app.jar"
  coupon_jar_key  = "coupon/${var.coupon_build_id}-${local.coupon_jar_sha256}/app.jar"
}

resource "aws_s3_bucket" "artifacts" {
  bucket_prefix = "${local.name_prefix}-artifacts-"

  tags = {
    Name = "${local.name_prefix}-artifacts"
  }
}

resource "aws_s3_bucket_public_access_block" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_object" "product_jar" {
  bucket      = aws_s3_bucket.artifacts.id
  key         = local.product_jar_key
  source      = var.product_jar_path
  source_hash = filebase64sha256(var.product_jar_path)

  metadata = {
    sha256 = local.product_jar_sha256
  }

  depends_on = [
    aws_s3_bucket_ownership_controls.artifacts,
    aws_s3_bucket_public_access_block.artifacts,
    aws_s3_bucket_server_side_encryption_configuration.artifacts,
  ]
}

resource "aws_s3_object" "coupon_jar" {
  bucket      = aws_s3_bucket.artifacts.id
  key         = local.coupon_jar_key
  source      = var.coupon_jar_path
  source_hash = filebase64sha256(var.coupon_jar_path)

  metadata = {
    sha256 = local.coupon_jar_sha256
  }

  depends_on = [
    aws_s3_bucket_ownership_controls.artifacts,
    aws_s3_bucket_public_access_block.artifacts,
    aws_s3_bucket_server_side_encryption_configuration.artifacts,
  ]
}

resource "aws_ssm_parameter" "db_admin_password" {
  name   = "/${local.name_prefix}/db/admin-password"
  type   = "SecureString"
  key_id = "alias/aws/ssm"
  value  = var.db_admin_password
}

resource "aws_ssm_parameter" "db_app_password" {
  name   = "/${local.name_prefix}/db/app-password"
  type   = "SecureString"
  key_id = "alias/aws/ssm"
  value  = var.db_app_password
}

data "aws_iam_policy_document" "ec2_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "product" {
  name_prefix        = "${local.name_prefix}-product-"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume_role.json
}

resource "aws_iam_role" "coupon" {
  name_prefix        = "${local.name_prefix}-coupon-"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume_role.json
}

resource "aws_iam_instance_profile" "product" {
  name_prefix = "${local.name_prefix}-product-"
  role        = aws_iam_role.product.name
}

resource "aws_iam_instance_profile" "coupon" {
  name_prefix = "${local.name_prefix}-coupon-"
  role        = aws_iam_role.coupon.name
}

resource "aws_iam_role_policy_attachment" "product_ssm_core" {
  role       = aws_iam_role.product.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy_attachment" "coupon_ssm_core" {
  role       = aws_iam_role.coupon.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy_attachment" "product_cloudwatch_agent" {
  role       = aws_iam_role.product.name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy"
}

resource "aws_iam_role_policy_attachment" "coupon_cloudwatch_agent" {
  role       = aws_iam_role.coupon.name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy"
}

data "aws_iam_policy_document" "product_runtime" {
  statement {
    sid       = "ReadProductJar"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = [aws_s3_object.product_jar.arn]
  }

  statement {
    sid       = "ReadApplicationPassword"
    effect    = "Allow"
    actions   = ["ssm:GetParameter", "ssm:GetParameters"]
    resources = [aws_ssm_parameter.db_app_password.arn]
  }

  statement {
    sid       = "DenyAdministratorPassword"
    effect    = "Deny"
    actions   = ["ssm:GetParameter*"]
    resources = [aws_ssm_parameter.db_admin_password.arn]
  }

  statement {
    sid       = "DenyParameterPathReads"
    effect    = "Deny"
    actions   = ["ssm:GetParametersByPath"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "product_runtime" {
  name_prefix = "${local.name_prefix}-product-runtime-"
  role        = aws_iam_role.product.id
  policy      = data.aws_iam_policy_document.product_runtime.json
}

data "aws_iam_policy_document" "coupon_runtime" {
  statement {
    sid       = "ReadCouponJar"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = [aws_s3_object.coupon_jar.arn]
  }

  statement {
    sid     = "ReadDatabasePasswords"
    effect  = "Allow"
    actions = ["ssm:GetParameter", "ssm:GetParameters"]
    resources = [
      aws_ssm_parameter.db_admin_password.arn,
      aws_ssm_parameter.db_app_password.arn,
    ]
  }
}

resource "aws_iam_role_policy" "coupon_runtime" {
  name_prefix = "${local.name_prefix}-coupon-runtime-"
  role        = aws_iam_role.coupon.id
  policy      = data.aws_iam_policy_document.coupon_runtime.json
}
