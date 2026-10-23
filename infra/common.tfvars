aws_region   = "eu-west-1"
project_name = "tus-ca-csi"
availability_zones = [
  "eu-west-1a",
  "eu-west-1b"
]

db_instance_class = "db.t4g.micro"
coupon_ami_id     = "ami-051ef443317b2de18"
product_jar_path  = "../app/productservice/target/productservice-0.0.1-SNAPSHOT.jar"
coupon_jar_path   = "../app/couponservice/target/couponservice-0.0.1-SNAPSHOT.jar"

