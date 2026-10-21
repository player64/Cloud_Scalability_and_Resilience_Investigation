resource "aws_cloudwatch_log_group" "applications" {
  name              = "/${local.name_prefix}/apps"
  retention_in_days = 14
}
