# Non-secret experiment overrides; load after your shared common.tfvars.
# Keep builds, instance types, database, Coupon and timings fixed across profiles.
product_min            = 1
product_desired        = 1
product_max            = 1
enable_product_scaling = false
experiment_profile     = "baseline"
