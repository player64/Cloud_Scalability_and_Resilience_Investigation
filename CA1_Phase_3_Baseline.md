# CA1 — Phase 3: One-Instance Baseline

## Objective
Measure Product service performance under a **fixed, repeatable GET workload** with **one healthy EC2 Product instance**. These results become the reference for the two-instance comparison in Phase 4.

**Scope:** baseline setup, a small k6 workload, pilot selection, recorded measurement, and a short report update. **Do not perform instance-failure or recovery experiments in this phase.**

## 1. Verify the baseline

- [ ] Select and apply the existing `baseline.tfvars` configuration (using the project's normal Terraform workflow).
- [ ] Confirm the Product Auto Scaling Group has one **healthy ALB target**.
- [ ] Confirm the Product GET endpoint returns the expected, fixed fixture values.
- [ ] Confirm the response includes `X-Product-Instance`.
- [ ] Confirm EC2 CPU and basic RDS metrics are visible in CloudWatch.

**Exit criterion:** one healthy Product target, correct GET response, and available metrics.

## 2. Prepare a minimal k6 test

Create `load-tests/product.js` using:

- `constant-arrival-rate` with an explicitly recorded rate and duration.
- **Exactly one GET per iteration**: no retries, redirects, setup requests, or sleeps within the measured iteration.
- One native `check()` per response: HTTP 200 **and** all expected fixture fields/values match. Malformed JSON must fail the check.
- A check tag populated from `X-Product-Instance` (or `unknown` if absent).
- Explicit request timeout and enough preallocated/max VUs to avoid generator-side dropped iterations.

Save the k6 version and test-script revision. Example export (replace `RUN` with a unique directory):

```bash
mkdir -p evidence/RUN
K6_CSV_TIME_FORMAT=unix_milli k6 run \
  --out csv=evidence/RUN/k6.csv \
  load-tests/product.js > evidence/RUN/k6.txt 2>&1
```

**Exit criterion:** a short smoke test exports a valid CSV and summary, with one correctness check per completed GET and a usable instance tag.

## 3. Run short pilots

- [ ] Try increasing fixed GET rates, one short run at a time.
- [ ] Inspect achieved requests/s, p95 latency, HTTP errors, correctness failures, dropped iterations, and Product EC2 CPU.
- [ ] If k6 drops iterations, first increase VUs **without changing the offered rate**.
- [ ] Choose a rate that gives a meaningful workload without making the load generator the bottleneck.
- [ ] Choose a stable warm-up period and recorded duration long enough to collect several one-minute CloudWatch samples (aim for at least three).

**Exit criterion:** a defensible rate, warm-up, duration, VU limits, and timeout have been selected from pilot evidence.

## 4. Freeze the comparison protocol

Record these before the formal run; **reuse them unchanged in Phase 4**:

| Parameter | Selected value |
| --- | --- |
| Product GET URL/path | TBD |
| Fixture identity / expected fields | TBD |
| Offered rate (iterations/s) | TBD |
| Warm-up duration | TBD |
| Recorded duration | TBD |
| `preAllocatedVUs` / `maxVUs` | TBD |
| Request timeout / graceful stop | TBD |
| k6 version / script revision | TBD |
| UTC run start / end | TBD |

Set provisional p95 and error objectives **before** interpreting recorded results. These are experiment objectives, not official service SLAs.

## 5. Record the one-instance baseline

1. Stop unrelated requests; restore and verify the fixed fixture.
2. Confirm **one healthy Product target**.
3. Run the same separate, read-only warm-up planned for Phase 4.
4. Verify the fixture remains unchanged.
5. Run the recorded k6 test and retain `k6.csv` and `k6.txt`.
6. Export CloudWatch metrics for the matching **absolute UTC** interval:
   - `AWS/EC2` → `CPUUtilization` for the Product `InstanceId` (**Average**, 60-second period; requires detailed monitoring for one-minute EC2 samples).
   - `AWS/RDS` → `CPUUtilization` and `DatabaseConnections` for the DB instance (**Average**, 60-second period).
7. Save a small configuration snapshot identifying the one-instance profile and instance type.

Use a new evidence directory for every recorded run. Aim for **two matched baseline/comparison pairs** if practical; if only one is possible, report that repeat variability is unknown.

## 6. Analyse and update the report

| Measurement | How to report it |
| --- | --- |
| Offered demand | Configured k6 iterations/s |
| Correct throughput | Passed response checks ÷ measurement-window seconds |
| p95 latency | 95th percentile of `http_req_duration` samples, in ms |
| HTTP failure rate | `http_req_failed` percentage |
| Incorrect response rate | Failed checks ÷ all checks × 100 |
| Dropped work | `dropped_iterations` count |
| Product CPU | CloudWatch average CPU (%) over the selected interval |
| RDS reference | RDS average CPU (%) and database connections |

Keep HTTP failures and incorrect responses **separate**; they can overlap. Use the same time-window boundaries and calculations in Phase 4. k6 HTTP samples are recorded at completion, so document any end-of-run drain and do not confuse scheduled iterations with completed requests.

**Report update:**
- **Method:** fixture and GET, chosen rate and duration, pilot justification, warm-up, correctness rule, and measurement definitions.
- **Results:** baseline row and clearly labelled chart(s), including unexpected behaviour.
- **Limitations:** a single offered rate does **not** establish maximum system capacity; RDS metrics alone do not prove a database bottleneck.

## Phase 3 completion checklist

- [ ] One healthy Product target verified.
- [ ] Fixed fixture and correctness check verified.
- [ ] k6 pilot completed; settings frozen.
- [ ] Baseline CSV and summary saved.
- [ ] Product CPU and RDS metrics exported.
- [ ] Baseline measurements calculated and documented.
- [ ] Identical comparison protocol ready for Phase 4.

**Next:** Phase 4 — repeat the same workload with two healthy Product instances and compare like-for-like results.
