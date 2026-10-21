# AWS manages the target-tracking alarms; do not duplicate them in Terraform.
resource "aws_autoscaling_policy" "product_cpu" {
  count = var.enable_product_scaling ? 1 : 0

  name                   = "${local.name_prefix}-product-cpu"
  autoscaling_group_name = aws_autoscaling_group.product.name
  policy_type            = "TargetTrackingScaling"

  target_tracking_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ASGAverageCPUUtilization"
    }
    target_value     = var.product_cpu_target
    disable_scale_in = false
  }
}
