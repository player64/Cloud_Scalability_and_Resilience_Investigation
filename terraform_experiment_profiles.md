# Terraform Experiment Profiles — CA1

Use Terraform to select the Product Auto Scaling Group (ASG) configuration **before** each experiment. Run these commands yourself from the Terraform root; the AI agent must not run `terraform plan`, `apply`, `destroy` or AWS CLI commands.

## Profiles at a glance

| Profile | Min / desired / max | CPU target tracking | What it tests |
| --- | --- | --- | --- |
| `baseline.tfvars` | 1 / 1 / 1 | Off | Performance with one Product instance |
| `scaled.tfvars` | 2 / 2 / 2 | Off | Performance with two fixed Product instances |
| `elasticity.tfvars` | 1 / 1 / 2 | On, 50% target | Automatic capacity changes as CPU demand changes |
| `failure.tfvars` | 2 / 2 / 2 | Off | Availability and ASG replacement after an instance failure |

**Min** is the minimum permitted instance count; **desired** is the count the ASG aims to maintain; **max** is its upper limit. CPU target tracking is distinct from ASG health-based instance replacement: even when scaling is off, the ASG still replaces failed instances.

## Phase 3 — One-instance baseline

```bash
terraform plan -var-file=terraform.tfvars -var-file=baseline.tfvars
terraform apply -var-file=terraform.tfvars -var-file=baseline.tfvars
```

Review the plan before applying. Wait for **one healthy Product target** behind the ALB, then run the fixed-fixture k6 workload. Record throughput, p95 latency, errors, dropped iterations, Product CPU and basic RDS metrics.

## Phase 4 — Two-instance comparison

```bash
terraform plan -var-file=terraform.tfvars -var-file=scaled.tfvars
terraform apply -var-file=terraform.tfvars -var-file=scaled.tfvars
```

Wait for **two healthy Product targets**. Repeat the **same** k6 request rate, duration, fixture and measurement method used for the baseline. Compare results to see whether the second instance improves performance. Scaling is **fixed**, not automatic.

## Later — Elasticity

```bash
terraform plan -var-file=terraform.tfvars -var-file=elasticity.tfvars
terraform apply -var-file=terraform.tfvars -var-file=elasticity.tfvars
```

The ASG starts with one desired instance and may grow to two under its **50% CPU target-tracking policy**, then scale in when demand decreases. The 50% target is **not** an immediate trigger. Observe actual capacity, target health, policy activity and k6 responses while load changes.

## Later — Failure recovery

```bash
terraform plan -var-file=terraform.tfvars -var-file=failure.tfvars
terraform apply -var-file=terraform.tfvars -var-file=failure.tfvars
```

Start with **two healthy targets**. During the controlled failure experiment, terminate one Product instance manually and observe whether the remaining target serves requests while the ASG replaces the failed instance. Record the recovery interval and any errors.

## Rules for fair experiments

1. Always supply **both** variable files, with `common.tfvars` first and exactly one experiment profile second.
2. Inspect each Terraform plan; when changing profiles, expect capacity and scaling-policy changes, not unrelated infrastructure replacements.
3. **Never run Terraform apply during a recorded measurement.** For elasticity, AWS changes capacity through the scaling policy; applying Terraform afterwards may intentionally reset desired capacity.
4. Wait until the required ALB targets are healthy before starting fixed-capacity measurements.
5. Keep instance types, application versions, database, fixture, k6 workload and measurement method consistent across the Phase 3/4 comparison.
6. Use the AWS Console/CloudWatch to observe and export evidence, not to manually change Terraform-managed ASG capacity.

**Summary:** Terraform sets the experiment profile; k6 generates demand; ALB routes requests; CloudWatch and k6 provide evidence. Only the elasticity profile enables CPU-driven automatic scaling.
