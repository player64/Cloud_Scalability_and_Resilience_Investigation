aws_region   = "eu-west-1"
project_name = "tus-ca-csi"
availability_zones = [
  "eu-west-1a",
  "eu-west-1b"
]

db_instance_class = "db.t4g.micro"
coupon_ami_id     = "ami-051ef443317b2de18"
# Canonical Ubuntu Server 24.04 LTS amd64, eu-west-1, 2026-10-04 release.
# Source: https://cloud-images.ubuntu.com/releases/server/streams/v1/com.ubuntu.cloud:released:aws.json
load_generator_ami_id = "ami-071f50ad836e28841"
product_jar_path      = "../app/productservice/target/productservice-0.0.1-SNAPSHOT.jar"
coupon_jar_path       = "../app/couponservice/target/couponservice-0.0.1-SNAPSHOT.jar"

load_generator_instance_type = "c7i.xlarge"