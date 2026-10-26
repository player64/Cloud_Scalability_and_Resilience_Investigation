# Non-secret experiment overrides; load after your shared common.tfvars.
# Keep builds, instance types, database, Coupon and timings fixed across profiles.
product_min            = 2
product_desired        = 2
product_max            = 2
enable_product_scaling = false
experiment_profile     = "failure"
