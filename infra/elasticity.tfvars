# Non-secret experiment overrides; load after your shared common.tfvars.
# Keep builds, instance types, database, Coupon and timings fixed across profiles.
product_min            = 1
product_desired        = 1
product_max            = 2
enable_product_scaling = true
product_cpu_target = 30