# CA1 — Cloud Scalability and Resilience: Next Stage

**Status:** AWS infrastructure deployed; Terraform experiment profiles prepared.  
**Next objective:** Establish a reproducible **one-instance baseline**, collect evidence, then repeat under **two-instance scaling**. Elasticity and failure recovery follow later.

> The assignment deadline was extended by 10 days. Confirm the revised submission date in Moodle; do not assume a specific date from this note.

## 1. Confirm baseline infrastructure

Use the Terraform directory containing the existing files. You already have `terraform.tfvars` — **do not create `common.tfvars`**.

```bash
terraform plan -var-file=terraform.tfvars -var-file=baseline.tfvars
terraform apply -var-file=terraform.tfvars -var-file=baseline.tfvars
```

**You run these commands manually.** Review the plan before applying. The AI agent must not run `terraform plan`, `apply`, `destroy`, AWS CLI, or access AWS credentials.

Verify in the AWS Console:

- Product Auto Scaling Group: **1 desired / 1 healthy instance**.
- ALB target group: **1 healthy Product target**.
- Product GET endpoint through the ALB: HTTP 200 and the expected fixed product fixture.
- Coupon service and RDS are reachable through the existing application flow.
- CloudWatch log group **`/tus-ca-csi/apps`** contains recent Product logs, typically `<instance-id>/product`.
- CloudWatch EC2 and RDS metrics are visible.

**Do not start a measured run until the application and target health are stable.**

## 2. Prepare one simple k6 script

Create `load-tests/product.js` using the actual, verified Product GET endpoint and response structure. Do not guess the endpoint or fixture.

Requirements:

- **One GET request per iteration**; no POSTs, retries, redirects, or sleeps in measured iterations.
- `constant-arrival-rate` executor; configurable request rate and duration.
- Explicit HTTP timeout and sufficient VUs to avoid `dropped_iterations`.
- Check HTTP 200 **and** the expected fixture fields (a single combined `check` is sufficient).
- Retain native k6 metrics: `http_reqs`, `http_req_duration`, `http_req_failed`, `checks`, and `dropped_iterations`.
- If the response includes `X-Product-Instance`, tag samples with it for later analysis.
- Do **not** build custom evidence-collection tooling or modify the Java applications.

Before implementation, inspect the actual GET response to decide what the checks should assert.

## 3. Pilot: choose a useful workload

Run short, separate trials with illustrative starting rates such as **5, 10 and 20 requests/second**, for approximately **60 seconds each**. These are starting points, **not** known capacity limits.

For each trial, look at:

- Achieved request rate and `dropped_iterations`.
- p95 response time.
- HTTP failures and failed response checks.
- Product EC2 CPU; RDS CPU and database connections.

Choose a rate that provides a meaningful comparison between one and two instances without overwhelming the k6 generator. Record why you selected it.

## 4. Run the formal baseline and save evidence

Create a unique evidence folder:

```bash
mkdir -p evidence/baseline-01
```

With your script configured for the selected workload, run:

```bash
K6_CSV_TIME_FORMAT=unix_milli \
k6 run --out csv=evidence/baseline-01/k6.csv \
  load-tests/product.js \
  > evidence/baseline-01/k6.txt 2>&1
```

Use a separate warm-up and a clearly recorded measurement interval. **Five minutes of measured load** is a practical initial target, subject to the assignment's actual requirements.

Save:

- `k6.csv` — native time-stamped metric samples.
- `k6.txt` — run output and final summary.
- `notes.md` — UTC start/end, Terraform profile, healthy target count, URL/path, fixture, k6 rate, VUs, duration, warm-up, and any anomalies.
- CloudWatch CSV exports and a few screenshots of relevant metrics.
- Relevant application log excerpts, if available.

**Keep the original k6 CSV.** Do not rely on screenshots or summary text alone.

## 5. Export AWS metrics and logs

Use the **AWS Console**; no new monitoring services are needed.

### Product EC2 CPU

CloudWatch → Metrics → All metrics → EC2 → Per-Instance Metrics → `CPUUtilization`.

- Statistic: **Average**.
- Period: **1 minute**.
- Select the Product instance ID for this run.
- Set the graph window to include the experiment and export CSV.

### RDS

CloudWatch → Metrics → All metrics → RDS → Per-Database Metrics.

Export:

- `CPUUtilization` — **Average**, **1 minute**.
- `DatabaseConnections` — **Average**, **1 minute**.

RDS utilisation provides context; it does **not**, by itself, prove a database bottleneck.

### Application logs

CloudWatch → Logs → Log groups → **`/tus-ca-csi/apps`** → Product stream, typically `<instance-id>/product`.

Find messages covering the test period and save relevant excerpts or screenshots. Logs are supporting evidence; **k6 is the source of truth for response latency and correctness**.

**Time alignment:** Record UTC start/end times and compare metrics from the same interval. CloudWatch data can appear with a delay, so wait for samples before exporting. k6 CSV timestamps are in Unix milliseconds when using the command above.

## 6. Repeat with two Product instances

Once baseline evidence is complete, manually switch profiles:

```bash
terraform plan -var-file=terraform.tfvars -var-file=scaled.tfvars
terraform apply -var-file=terraform.tfvars -var-file=scaled.tfvars
```

Verify **two healthy Product targets**, then run the same workload and save it under `evidence/scaled-01/`.

**Keep identical:** endpoint, fixture, rate, duration, warm-up procedure, k6 generator settings, and database/Coupon configuration. Do not apply Terraform during measured runs.

Compare:

- Successful throughput (correct responses per second).
- p95 latency.
- HTTP failures **separately** from failed content checks.
- Dropped iterations.
- Product CPU **per instance**.
- RDS CPU and database connections.

A small improvement, no improvement, or regression can all be valid results if accurately measured and explained.

## 7. Later — elasticity and resilience

**Elasticity (`elasticity.tfvars`):** Product ASG starts at one instance and can grow to two using CPU target tracking (default target 50%). Use a controlled rising workload; observe capacity changes, healthy targets, latency, errors and recovery to lower demand. Target tracking is **not an instantaneous 50% threshold switch**.

**Failure (`failure.tfvars`):** Start with two healthy instances. While k6 sends traffic, **manually terminate one Product EC2 instance**, then observe whether the ALB continues serving requests and how long the ASG takes to restore two healthy targets. Record request failures, latency and recovery timeline. ASG instance replacement is distinct from CPU-based scaling. The failure profile's capacity matches `scaled.tfvars`; its separate name documents the experiment.

Perform these **after** the baseline/scaled comparison works. No need to collect everything at once.

## 8. Minimal evidence directory

```text
evidence/
├── baseline-01/
│   ├── k6.csv
│   ├── k6.txt
│   ├── notes.md
│   ├── ec2-cpu.csv
│   ├── rds-cpu.csv
│   └── rds-connections.csv
└── scaled-01/
    └── ...same evidence types...
```

Save only real exports; do not create placeholder files just to fill this tree.

## Immediate next action

**Inspect the actual Product GET response and its expected fixture**, then prepare the single k6 script. After that, complete a 60-second pilot and confirm that both k6 evidence and CloudWatch measurements are available.
