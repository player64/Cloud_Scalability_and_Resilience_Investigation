# CA1: Cloud Scalability & Resilience Investigation — execution and report plan

## The argument you are building

**Central question:** to what extent does horizontally scaling the Product Service improve the scalability and resilience of the application, and what limitations remain elsewhere in the architecture?

Work towards an evidence-backed answer, not a predetermined claim that scaling succeeds. Establish the architecture, measure one Product instance, compare two instances under the same workload, observe automatic capacity changes, then remove an instance and measure recovery. Use those results to evaluate the complete application.

The report grows throughout this sequence. After each phase, write the method, observations and interpretation while the evidence is fresh. By the final phase, all substantive report sections should already contain your work.

| Status | What applies |
| --- | --- |
| **Official assessment requirements** | CA1 is worth **20%** of the module, due **27 October 2026**. Submit a technical report **and** an engineering evidence screencast of **at most six minutes**. |
| **Official architecture and investigation requirements** | Product must be stateless and capable of running as equivalent instances, with persistent state external to Product EC2 instances and one client endpoint. Demonstrate load distribution, health checking, repeatable instance creation, monitoring and capacity adjustment. Investigate baseline, horizontal scaling, elasticity, failure/recovery and remaining whole-system limitations. |
| **Your additional project constraint** | **Provision and manage the assignment's AWS infrastructure with Terraform.** This is mandatory for this project; it is not an extra requirement attributed to the lecturer. |
| **Recommended implementation choices** | An Application Load Balancer (ALB) provides the endpoint and distributes requests. An Auto Scaling group (ASG) maintains Product capacity and replaces instances. Use CloudWatch for monitoring and k6 for client load. RDS is the brief's preferred database platform. |
| **Values you determine** | Request mix/rate, test duration, instance type, scaling limits/target and startup allowances. Choose these using functional checks, pilot runs, observed behaviour and your resource budget. The recommended one-versus-two comparison is a chosen experimental design, not an official prescribed count. |

A stateless Product instance must not depend on locally retained request/session data; another equivalent instance must be able to serve the workload using the external state. Scalability concerns behaviour as demand grows; elasticity concerns automatic capacity changes; resilience concerns continued service and recovery during failure.

## Where the marks come from

| Criterion | Weight | What your work must demonstrate |
| --- | ---: | --- |
| Critical Engineering Evaluation | 25% | Explain what improved, what did not, why the evidence supports that judgement, what remains vulnerable and which improvement deserves priority. |
| Results & Quality of Evidence | 20% | Present comparable measurements and useful event timelines, with each figure supporting a specific claim. |
| Experimental Design & Method | 15% | Run a justified workload, identify what changed, retain the other settings and record enough detail to repeat the experiment. |
| Architecture & Engineering Rationale | 15% | Explain the responsibilities, dependencies and trade-offs of the deployed architecture. |
| Technical Implementation | 15% | Demonstrate working requests, equivalent instances, repeatable provisioning, healthy-target routing, automatic scaling and replacement. |
| Communication & Professional Presentation | 10% | Make the report readable and traceable; use the screencast to communicate the strongest evidence; reference sources and declare AI assistance. |

Evidence and evaluation together account for **45%**. Reserve time to examine results and update the report after every run, rather than spending the whole project deploying infrastructure.

## Start the report immediately

In phase 1, create the report using the six section names in the official brief. These are the destinations for every subsequent report update.

| Report section | What it will contain as the investigation develops |
| --- | --- |
| **1. Problem & Architecture** | Central question, application request flow, deployed architecture, constraints, dependencies and reasons for the main design choices. |
| **2. Experimental Method** | Workload and data, environment, metrics, warm-up, run duration, comparison settings, elasticity stages and failure procedure. |
| **3. Technical Implementation** | Selected evidence that Terraform and application deployment produce the required behaviour; relevant configuration values and functional checks. |
| **4. Results & Evidence** | Baseline, one-versus-two comparison, elasticity and failure results, with labelled tables/figures and explanations of the observed behaviour. |
| **5. Engineering Evaluation** | What the results mean for scalability and resilience, remaining bottlenecks and single points of failure, trade-offs and one prioritised next improvement. |
| **6. Communication & Referencing** | Referenced sources and transparent AI-use declaration. Clear structure, diagrams and captions also apply throughout the report. |

Put measured changes and their immediate interpretation in **Results & Evidence**. Put their significance, limitations and the answer to the overall question in **Engineering Evaluation**. Do not create a separate “Discussion” chapter merely because the plan asks you to discuss results.

Keep the project small. A suitable working area is `assessment/practice/ca1/`, or a separate assignment repository. Copy the supplied application into a working area if changes are needed; preserve this study repository's source inputs.

```text
app/                    Working application and repeatable startup instructions
infra/                  Terraform configuration and experiment variable files
load-tests/             k6 workload, staged workload and required test data
evidence/<run-name>/     Raw outputs, selected graphs/logs and actual run settings
report/report.md        The report, updated after every phase
```

These are suggested working directories, not extra submission requirements. Write decisions and run descriptions directly into the report; keep supporting raw data in evidence folders. As you finish each experiment, mark one useful report figure as a candidate for the screencast.

## Phase 1 — Establish the application and start the engineering argument

**Question → Why:** which requests use Product, Coupon and the database, and which of those paths are you actually testing? This prevents a Product-only result being presented as proof about the whole application.

**Setup:** copy [Product](../../source/03_week/Labs/productservice/) and [Coupon](../../source/03_week/Labs/couponservice/) into your working area. Their `pom.xml` files declare Java 17; their `src/main/resources/application.yml` files use MySQL database `servicedb`, Product port **9090** and Coupon port **9091**. Check Java/Maven and run `mvn clean package` in each working copy before paying for AWS. Resolve any supplied dependency/build incompatibility in that copy and record the version actually used.

**Do:**

- [ ] Inspect both controllers, entity classes, configuration and `sql/tables.sql`. Set up local MySQL, create `servicedb`, run the corrected schema, then start Coupon and Product using their packaged JARs and local configuration.
- [ ] Correct the working SQL to match the entities: the supplied Product SQL omits the persisted `couponCode` column (normally `coupon_code`). Check generated-ID types and mapped column names too. Preserve the original source files.
- [ ] Seed a known coupon, then POST a Product with a known original price and coupon code. Check the returned price equals original price minus discount and that GET returns the saved Product. Do not reuse an already-discounted response as the next POST input.
- [ ] Use the following bounded workload. It exercises Product and MySQL without changing the amount of data returned during the comparison.

| Operation | Input / correct result | Dependency and use |
| --- | --- | --- |
| `POST /productapi/products` | Fresh name/description, original price and known coupon code; correct saved fields and discounted price | Product → Coupon → database, and Product → database. Functional check before load tests, not part of measured load. |
| `GET /productapi/products` | No body; status 200 and the complete expected fixture set, comparing IDs/fields/prices without assuming row order | Product → database; **the measured workload**. It does not call Coupon. |
| `GET /couponapi/coupons/{code}` | Known code returns its seeded discount | Setup/dependency check on the Coupon host, outside measured traffic. |

Choose a small fixed product fixture set, save its SQL and expected values, and keep its row count/content identical for every recorded experiment. This choice deliberately leaves Coupon performance under load untested; its functionality and architectural failure exposure still belong in the evaluation.

**Collect:** the working build revision, operation inputs/expected responses and an initial request-flow diagram. No performance measurements are established yet.

**Analyse:** ask four questions to answer later: does one versus two Product instances change correct throughput/p95/errors; does automatic capacity arrive before clients suffer; does one survivor continue service during replacement; and what remains shared or untested? Expectations based on the code are hypotheses, not conclusions.

**Update report:** in **Problem & Architecture**, describe those actual calls, state location, increasing-demand/instance-loss problem and proposed ALB/Product arrangement. In **Experimental Method**, use the operation table to explain the selected read workload and excluded Coupon load path. Start **Communication & Referencing**. Do not write performance or resilience findings in Evaluation yet.

## Phase 2 — Build a reproducible Terraform deployment

**Question → Why:** can a fresh Product instance serve the same application without manual repair? Scaling and replacement depend on that capability.

### Setup: one small deployment path

Use one AWS account/region, one Terraform root and one local state file kept securely and backed up outside version control. Verify `aws sts get-caller-identity`, account permissions for the resources below and `iam:PassRole` before deployment. Use the same credentials/region for later observations. Prefer a fixed **non-burstable** Product instance type to avoid CPU-credit history; choose an affordable permitted size and retain it across experiments.

| Terraform provisions | Selected layout and connection |
| --- | --- |
| VPC, Internet Gateway, routes and subnets | Two public subnets in different Availability Zones, plus two private database subnets. Public routes lead to the Internet Gateway. Product/Coupon receive public IPv4 addresses for outbound downloads/AWS API access; no NAT gateway is needed. |
| ALB, listener, instance target group | Internet-facing ALB in both public subnets; HTTP listener forwards to Product port 9090. Allow the listener from the load-generator/student public IP range. Use non-sensitive test data; discuss HTTP/public-instance exposure as a lab trade-off. |
| Product launch template and ASG | Product instances in the public subnets, no direct inbound client access. ASG uses a pinned template version and registers instances with the target group. The **ASG manages instances; it is not a request-processing hop**. |
| One Coupon EC2 instance | Fixed public-subnet instance, port 9091 reachable from Product's security group. Product receives its **private IP** in `couponService.url=http://<private-ip>:9091/couponapi/coupons/`. Keep Coupon unchanged during tests. |
| One RDS MySQL instance | Single-AZ, not publicly accessible, database `servicedb`, private DB subnet group. Port 3306 accepts Product and Coupon security groups only. RDS endpoint supplies both JDBC URLs. |
| Artefacts and configuration | Private S3 bucket plus Terraform-managed artefact objects; non-secret outputs expose ALB/ASG/target-group/RDS identifiers. Two SSM SecureString parameters hold database admin and application passwords; credentials are not printed in evidence. |
| Instance profiles and administration | SSM Session Manager replaces SSH. Instance roles have SSM managed-instance permissions, read access to their S3 artefacts/app-password parameter, and Product log-delivery permissions. Only the Coupon/admin host also reads the DB-admin parameter. |
| Native monitoring | Product EC2 detailed monitoring for one-minute CPU; CloudWatch log group/agent configuration below. One Terraform target-tracking policy is enabled only for elasticity. |

No custom domain, NAT gateway, remote-state service, container platform, deployment pipeline or module library is needed. SSM and S3 requests use outbound HTTPS through the public route; a public subnet **without** a public address would not provide that route to the internet.

Use `versions.tf`, `main.tf`, `variables.tf`, `outputs.tf` and a startup template as needed. Commit the provider lock file. Keep shared non-secret values in `common.tfvars`, and expose `product_min`, `product_desired`, `product_max`, `enable_product_scaling`, policy target and startup/health timers.

| Profile | Product min / desired / max | Demand scaling |
| --- | --- | --- |
| Bootstrap, before database initialisation | 0 / 0 / 1 | Off |
| Baseline | 1 / 1 / 1 | Off |
| Scaled comparison | 2 / 2 / 2 | Off |
| Elasticity | 1 / 1 / 2 | On |
| Failure | 2 / 2 / 2 | Off; replacement stays on |

These counts are the selected minimal experiment, not lecturer-prescribed values. Run from `infra/`, using the appropriate profile:

```bash
terraform init
terraform fmt
terraform validate
terraform plan -var-file=common.tfvars -var-file=bootstrap.tfvars -out=run.tfplan
terraform apply run.tfplan
```

### Do: apply → initialise → start → verify

1. **Package and deliver:** build both JARs locally, record their revision/checksum, and have Terraform upload them to immutable S3 keys containing that build ID. Pin an Amazon Linux image with a compatible Java 17 runtime. Launch-template user data uses `base64encode(templatefile(...))`; it installs the runtime/required AWS agents, downloads the pinned artefact, and writes the service/configuration files. Do not rebuild code on each Product instance.
2. **Create the bootstrap infrastructure:** apply the zero-Product profile. Coupon's startup installs its artefact, MySQL client and systemd service. Use SSM to open a session on Coupon; this is the administration route to private RDS.
3. **Initialise the database once:** from that session, retrieve the admin credential without echoing it and run the versioned SQL against the RDS endpoint. Create/correct tables, a `ca1_app` user with the required data privileges, the known coupon and fixed Product fixtures. Application credentials come from the app-password parameter. Set runtime `spring.jpa.hibernate.ddl-auto=none`: replacements neither alter schema nor reseed data.
4. **Start Coupon:** systemd runs the JAR with port 9091 and the RDS JDBC URL/app credentials in a protected local configuration file. Verify the known coupon via localhost. Use `systemctl status` and `journalctl -u coupon` if it fails.
5. **Apply the baseline profile:** Product bootstrap obtains its instance ID using IMDSv2 (EC2's token-protected instance metadata), app password and configuration. Its systemd service runs on 9090 with the RDS URL and Coupon private URL. A startup pre-check retries the DB connection and known Coupon request at a short interval up to a documented limit; on expiry, log the failure rather than declaring success. Use `Restart=on-failure` with a bounded retry allowance. Initial schema work belongs to step 3, not this pre-check.
6. **Verify through the ALB:** wait for a healthy Product target, run the known POST and GET correctness checks, then restore the fixed fixture set via the Coupon/SSM administration route. The replacement will use the same artefact, external state and configuration.

If a build, bootstrap or Coupon address changes, create a new template version, update the ASG reference and use an ASG instance refresh **between experiments**. Wait for completion; verify every member's actual build/template. A template update does not retrofit running instances. Repeat the baseline if shared settings changed.

### Minimal readiness, attribution and durable logs

The existing controllers do not identify the serving instance. **One small application change is justified:** return `X-Product-Instance` on Product responses, populated from the bootstrap instance-ID environment value by a response filter. A body-correctness result and this header come from the **same response**, so a native k6 check can establish that a particular new instance served useful work. AWS target counts/status alone cannot do this. No tracing, request-ID scheme, response-body logging or custom request-data format is needed.

Use existing facilities for the rest:

- Enable Spring Boot Actuator readiness probes: `management.endpoint.health.probes.enabled=true`; include `readinessState,db` in `management.endpoint.health.group.readiness.include`. Use **GET `/actuator/health/readiness` returning 200** as the observable ready signal. It indicates application acceptance and database health, not proven throughput or Coupon health.
- Target-group health checks call that path on 9090 with matcher 200. The ASG's `health_check_type="ELB"` makes load-balancer health relevant to replacement. `health_check_grace_period` protects a starting instance from premature ASG health judgement; it does not force the ALB to send traffic to it.
- Keep ordinary Spring logs in `/var/log/ca1/product.log` using `logging.file.name`. Enable native Tomcat access logging to `/var/log/ca1/access/`, including UTC time, method/path, status and the response header (`%{X-Product-Instance}o`). This records requests and readiness probes without logging bodies.
- Bootstrap installs and starts the CloudWatch agent. Its `logs.logs_collected.files.collect_list` tails those two file paths into `/ca1/product`, using streams `{instance_id}/app` and `{instance_id}/access`. Terraform creates the log group and a modest retention period; the instance profile includes `CloudWatchAgentServerPolicy`. Start the agent with its native `amazon-cloudwatch-agent-ctl -a fetch-config -m ec2 -s -c file:<configuration>` command. A log group without this running collector does not capture logs.
- In CloudWatch Logs, find an actual Product request and a successful readiness probe from the instance. Already-delivered records survive instance deletion; the final buffered lines may not. Client-side native k6 results remain the source of correctness and errors.

**Collect:** deployed diagram, non-secret Terraform/profile/build references, successful functional responses, and the log/readiness observations above. Phase 3 contains the single evidence rehearsal before any recorded experiment.

**Analyse:** a healthy endpoint and correct fixture response establish working startup for this configuration. They do not yet establish scaling benefit or uninterrupted service.

**Update report:** **Problem & Architecture** gets solid request-flow arrows (client → ALB → Product → dependencies) and a separate management arrow from ASG to Product. Justify the shared endpoint, external state, repeatable startup, security-group paths and the deliberately single Coupon/RDS deployment. **Technical Implementation** gets selected Terraform/bootstrap settings and functional evidence. **Experimental Method** gets the actual build, instance types, region and dependency configuration.

Apply changes only between runs. During elasticity the ASG legitimately changes desired capacity; do not apply Terraform while measuring. Review the next plan as an intentional reset. Keep state/plans and credentials secure and out of shared evidence; no advanced lifecycle rule is needed.

## Phase 3 — Establish the one-instance baseline and justify the method

**Question → Why:** what does one Product instance deliver under known demand? This supplies the reference values and the pilot evidence for load and policy choices.

**Setup:** baseline profile, one healthy target, fixed fixture GET workload. Use the following **Measurement & Evidence procedure** for all experiments; later phases specify only the additional events and comparisons.

### Measurement & Evidence — one procedure

#### A. Define native k6 measurements once

Check `k6 version` and retain the version used. In the student workload file:

- Use `constant-arrival-rate` with `rate=R`, `timeUnit="1s"` and the chosen `duration`. A fixed arrival rate means k6 schedules **R iterations each second**, regardless of earlier response times. Make each iteration exactly one GET: no branching, redirects (`redirects: 0`), retries, extra setup calls or sleep.
- VUs are concurrent execution workers. Set `preAllocatedVUs` and `maxVUs` high enough that pilots sustain the rate; slow responses occupy workers. `dropped_iterations` counts scheduled work that never started, not server errors.
- Set an explicit request timeout and `gracefulStop` longer than that timeout so outstanding requests can finish after scheduled load ends. Keep those values unchanged in a pair.
- Set the HTTP expected-status rule to 200. Use **one combined native `check()` per response**, true only for status 200 and the complete expected fixture set. Catch malformed JSON and return false. Comparing ten fields still produces one request-level boolean, not ten checks.
- Tag that check with the response's instance header. For illustration, after implementing the fixture predicate:

```javascript
check(response, { 'correct Product response': r => validFixture(r) },
      { instance: response.headers['X-Product-Instance'] || 'unknown' });
```

This uses native `checks` samples: value 1 for correct, 0 for incorrect. HTTP failures and failed correctness checks overlap; report them separately, never add their percentages. Successful throughput comes from passed request-level checks, not all `http_reqs`. Do not count health/setup requests as workload.

For elasticity, change only the executor to `ramping-arrival-rate`: `startRate` is the initial iterations/second, and `stages: [{target: rate, duration: holdOrRamp}, ...]` reaches each target over its duration. Repeating the same target holds it steady. Preserve the GET and checks.

Create a separate evidence directory for each run. A native export command, after supplying your workload's actual inputs, is:

```bash
K6_CSV_TIME_FORMAT=unix_milli k6 run --out csv=evidence/RUN/k6.csv load-tests/product.js > evidence/RUN/k6.txt 2>&1
```

The CSV is k6's standard format, not a custom event file. Save script/profile revisions and actual rate, VU limits, timeout, fixture and UTC run boundaries in the report's method notes.

#### B. Capture AWS observations with existing tools

CloudWatch **dimensions** select the resource, such as `InstanceId=i-...`. **Period** is the time bucket, and **statistic** describes its values: Average CPU is not maximum CPU. One-minute graphs require one-minute source data; selecting a finer graph period cannot create it.

In CloudWatch **Metrics → All metrics**, select the exact series below, then **Graphed metrics** to set statistic/period. Set an absolute UTC start/end matching the experiment, download the graph data as CSV and save the labelled graph if it supports a report claim. Wait for delayed samples to arrive before exporting.

| Required observation | Source → exact series/event and selector | Collection/statistic/unit | Window → saved evidence |
| --- | --- | --- | --- |
| Throughput, p95, errors, dropped work | Native k6 `checks`, `http_reqs`, `http_req_duration`, `http_req_failed`, `dropped_iterations` | Native CSV/summary; calculations in C below; requests/s, ms, %, counts | Whole run plus named client windows → `k6.csv`, `k6.txt`, result table |
| Product host CPU | `AWS/EC2 / CPUUtilization`, dimension `InstanceId` for each tested member | Average, 60-second period, Percent; detailed monitoring enabled in template | Baseline/comparison and survivor period → CPU CSV/graph; host CPU, not Java-process CPU |
| Small dependency reference | `AWS/RDS / CPUUtilization` and `DatabaseConnections`, dimension `DBInstanceIdentifier` | Average, 60-second period, Percent and Count | Baseline/comparison windows → RDS CSV; connection count is not query-wait time |
| Elasticity policy response | `AWS/ApplicationELB / RequestCountPerTarget`, dimensions `LoadBalancer` and `TargetGroup` using ARN suffixes | **Sum**, 60-second period; this metric represents average requests per target per minute despite the statistic name | Elasticity run → metric CSV/graph, policy settings |
| Target state and actual capacity | ELBv2 `describe-target-health`; ASG `describe-auto-scaling-groups` | Native CLI snapshots below; target ID/state/reason, desired count and member lifecycle states | Throughout elasticity/failure → timestamped `states.txt`; start/end view suffices for fixed runs |
| Launch/scale/replacement cause | ASG **Activity**, EC2 instance details | Activity start/cause/status, instance ID/launch time; save native CLI activity JSON or relevant Console entries | Event runs → activity export and instance details |
| Readiness and useful service | Existing CloudWatch app/access streams; native k6 `checks` tagged `instance` | Readiness HTTP 200; earliest check value 1 for new instance; UTC sample times | Event runs → selected log export and corresponding k6 row |
| Whole-system/cost basis | Terraform configuration and AWS instance inventory | Counts/types, RDS single-AZ setting, access rules, observed running interval | Configuration revision for each run → small inventory; no billing-analysis project |

For transient states, use a separate terminal on the load-generator/student machine, **not on Product**. Set `TG` and `ASG` from Terraform outputs, use a new `RUN` directory, and disable CLI paging with `export AWS_PAGER=""`. Run this observation-only loop before starting elasticity/failure load; stop with Ctrl-C after recovery/observation ends:

```bash
while true; do
  date -u '+SAMPLE_START %Y-%m-%dT%H:%M:%SZ'
  aws elbv2 describe-target-health --target-group-arn "$TG" --output json
  aws autoscaling describe-auto-scaling-groups --auto-scaling-group-names "$ASG" --output json
  date -u '+SAMPLE_END %Y-%m-%dT%H:%M:%SZ'
  sleep 5
done > evidence/RUN/states.txt 2>&1
```

No target filter is used, so new targets appear automatically. The ASG output contains member IDs, lifecycle states and desired capacity. Count **InService** members separately from targets reported **healthy**; desired is the requested number, not proof that it exists. Save EC2 ID/private-IP/launch-time details for initial and replacement instances from the Console. Preserve errors/gaps in the capture. Five seconds is a practical polling choice, not exact event resolution: report transitions between surrounding snapshots and include query time.

After an event run, `aws autoscaling describe-scaling-activities --auto-scaling-group-name "$ASG" --output json` provides a native export to retain. No ASG metrics dashboard or AWS wrapper is required.

#### C. Turn exported samples into report windows

Use a spreadsheet, not a new analysis system. Import k6 CSV with `timestamp` numeric (Unix milliseconds), `metric_name`, `metric_value`, `check` and `extra_tags`. Convert a timestamp to UTC for display with `DATE(1970,1,1)+timestamp/86400000`.

1. Make a short window table: **name, UTC start, UTC end, duration in seconds**. Use half-open intervals: start included, end excluded. Select windows using scheduled demand changes and observed health/useful-capacity events, not favourable-looking results.
2. Filter by the interval and metric. Sum `http_reqs` for finished request attempts; count `checks` rows for checked responses; sum their values for correct responses. Correct responses/window seconds gives observed successful throughput. Failed correctness percentage is `100 × (checks count − checks sum) / checks count`. HTTP failure percentage is `100 × AVERAGE(http_req_failed values)`.
3. Calculate p95 with `PERCENTILE.INC(selected http_req_duration values, 0.95)` in milliseconds. Copy the filtered values to a small sheet if your spreadsheet cannot calculate over filters directly. Include failed requests in this defined latency series and interpret it alongside errors; fast failures are not a performance win.
4. Filter successful `checks` rows by the `instance=...` value in `extra_tags`. Their timestamps identify correct responses from each instance; the earliest for a new member is the **first observed useful response**, not necessarily its first-ever request.
5. Keep raw data and the calculation sheet. Full-run checks count should equal `http_reqs` with this one-request/one-check script; reconcile missing rows or interrupted iterations before using results. Do not sum different metric rows as if each were a request.

**Window convention:** native HTTP samples occur at completion/timeout; the check is recorded immediately afterwards. Windows therefore describe completed/checked work, not when requests began. Retain the end-of-run drain separately from scheduled load. Boundary samples may land in adjacent buckets; use the same rules for all runs and do not claim exact request-start or routing-stop times. Empty windows have no p95/error percentage; show counts and “no samples”. Flag sparse windows (for example, fewer than 20 responses) and avoid strong percentile claims. Never average window p95 values to obtain a whole-run p95.

Illustrative calculation only: in a 60-second window, 600 checked responses with 594 passes give 9.9 correct requests/s and 1% incorrect responses. Calculate p95 from the 600 relevant duration samples, not from those two totals. These numbers are not expected experimental results.

#### D. One short rehearsal before recorded experiments

- [ ] Send a known-correct GET and, in a **separate smoke run**, a deliberately wrong expected fixture. Confirm one passing and one failing native check, correct counts and instance tags. Return to the correct predicate before load.
- [ ] Confirm the instance header, readable Product access/startup logs in CloudWatch, a readiness 200 and at least one exportable Product CPU/RDS sample. Calculate one spreadsheet window and match its full-run counts to the k6 summary.
- [ ] Start the CLI capture, terminate the sole rehearsal Product instance while desired remains one, and watch replacement. Confirm the saved capture includes the old/new IDs and states, the new instance returns correct fixture responses, and old **already-ingested** logs remain in CloudWatch.
- [ ] Stop the capture, save the ASG activity and check that state times, the new instance's successful k6 check and log stream can all be found. Do not repeat a full formal recovery analysis here. If evidence is missing, fix that collection step before recorded runs.

### Do: pilot, reset, warm up, record

- [ ] State provisional acceptable p95/error levels in Method before using them to judge tests. They are your chosen test objectives, not official service-level requirements.
- [ ] Run short pilots at increasing GET rates. If all demand is served with little latency change and low pressure, the test may be too light to reveal a benefit. If p95/errors rise or correct throughput falls behind demand, inspect the native results and Product/RDS measurements before attributing a cause.
- [ ] If k6 drops work, first increase available VUs while keeping demand fixed; slow responses can consume them. Investigate generator CPU/network only if it still cannot sustain demand. Freeze the resulting generator/VU configuration for recorded pairs.
- [ ] Choose a measured duration covering a settled interval and several one-minute samples; **at least three** such samples is a modest collection rule, not statistical proof. Use the pilot to choose the warm-up duration after response behaviour stops drifting.
- [ ] Before each recorded run: stop other requests → restore/verify the fixed fixture via Coupon/SSM → wait for the required healthy count → run the same **read-only** warm-up separately → verify fixture count/values remain unchanged → start the recorded GET workload. No measured POSTs, row growth or warm-up writes.
- [ ] Record baseline A. Aim for **two matched pairs**, A then B, across phases 3–4, using new filenames and the same protocol. If only one pair is affordable, explicitly report a descriptive comparison with repeat variation unknown. Additional repetitions/rate curves are optional.

**Collect:** baseline k6 files, Product CPU, the two basic RDS series, one-target confirmation and configuration/fixture reference. No startup timeline, Coupon timings or ALB access logs are required for this run.

**Analyse:** put correct requests/s, p95, HTTP/incorrect-response percentages, dropped work and CPU alongside offered rate and measurement interval. Note RDS observations without declaring it a bottleneck. One tested rate is not a maximum-capacity measurement.

**Update report:** **Method** gets the real GET/fixture predicate, pilot-based load/duration choices, collection/window definitions, reset/warm-up order and repetition decision. **Results** gets the baseline row and a useful graph with run/time/units, including unexpected behaviour. Do not write a scaling benefit yet.

## Phase 4 — Compare one Product instance with two

**Question → Why:** does changing only Product count improve the client outcome under the same offered work?

**Setup:** apply the two-instance profile, demand scaling off. Wait for two healthy targets; native successful checks tagged with both instance IDs establish that both served correct workload responses.

**Do:** use the same build/template, ALB, Product type, Coupon/database configuration, fixture, request rate, timeout, warm-up, duration, generator and VU settings as baseline. Run scaled A, then the second baseline/scaled pair if using the two-pair rule. If a shared setting changes, rerun both conditions; do not compare unlike runs.

**Collect:** the baseline minimum set plus two-target confirmation and successful native checks for each member. Retain the Terraform capacity change. Plot/table the runs side by side rather than selecting the best one.

**Analyse:** use **metric/unit | one Product | two Products | difference**. Calculate absolute change and `100 × (two − one) / one` where the denominator is non-zero. For error percentages distinguish percentage points from relative change. Show individual repeats; do not claim variation was measured if there was only one pair.

| Observation | Permitted interpretation / next check |
| --- | --- |
| More correct throughput or lower p95/errors at matched demand | A benefit for this workload; confirm actual delivered work/check counts and compare repeats. |
| Lower per-instance CPU only | More spare Product capacity, not a demonstrated client benefit or measured maximum capacity. |
| No clear change | Report it. Demand may already be fully served or another component may limit the outcome; the basic evidence may not distinguish those explanations. |
| Worse results | Preserve them. Check equivalent builds, healthy targets, fixture consistency and errors before blaming scaling itself. |
| RDS CPU/connections rise | More dependency demand; not proof that RDS caused a throughput limit. Deeper investigation is conditional, not a new required phase. |

**Update report:** **Method** states Product count as the changed variable and the repeated settings. **Results** contains the paired table, delivered demand and measured differences. **Evaluation** states which client outcomes improved or did not, under what load and with what repeat evidence. Avoid general linear-scaling, maximum-capacity or failure-resilience claims. Select this comparison for the screencast.

## Phase 5 — Test whether automatic scaling responds usefully

**Question → Why:** can demand trigger extra capacity that serves useful requests in time? This differs from the fixed one-versus-two comparison: detection and startup delays now matter.

**Setup:** use **one policy**, Terraform `aws_autoscaling_policy` with `policy_type="TargetTrackingScaling"`, `predefined_metric_type="ALBRequestCountPerTarget"`, `resource_label="<ALB arn_suffix>/<target-group arn_suffix>"` and a `target_value` in **requests per target per minute**. Attach it to the Product ASG and enable scale-in. AWS creates/manages its alarms.

Choose a sustainable per-instance rate from the pilots with margin before the chosen latency/error objective fails. Convert requests/s to the target with **60 × requests/s**: 10/s would be 600/minute, an illustration of units, not the chosen threshold. If no capacity pressure was reached, call the target exploratory. This request-based policy is suitable for the fixed-cost read workload; it does not detect database health.

Set ASG `default_instance_warmup` from the observed new-instance ready/useful delay plus a stated allowance. Scaling warm-up tells the policy how to treat newly added capacity; it neither probes readiness nor gates ALB traffic. Keep `health_check_grace_period` separately tied to avoiding premature replacement during startup.

**Do:**

- [ ] Apply elasticity min/desired/max **1/1/2**. Select low demand the initial instance handled, and high demand expected to exceed the per-target policy value while allowing two instances a useful test.
- [ ] Run one bounded pilot of the low–high–low stages with state capture. Record demand-rise-to-useful-capacity delay **D**. Before starting, set an affordable observation ceiling; if it expires without scale-out, stop and inspect the metric, policy activity, max count and startup errors. Correct the cause and rerun; do not leave the load running indefinitely.
- [ ] For the recorded run, make the high hold at least **D + W + one metric period**, where **W** is the settled measurement window chosen in phase 3. This leaves observations after new capacity becomes useful while demand is still high. Allow a low stage of W and a bounded return stage informed by the pilot's scale-in response; no observed scale-in remains reportable “where practical”.
- [ ] Start CLI capture before k6. Keep application, data, request behaviour and policy constant during the run; do not manually change capacity or apply Terraform.

**Collect:** native k6 output, `RequestCountPerTarget` graph/data, state snapshots, ASG Activity and selected new-instance readiness/startup logs. No extra diagnostics are required.

| Timeline point | Obtain from |
| --- | --- |
| Demand rise | k6 stage start recorded in UTC; completed-work samples confirm the workload response but are not request-start timestamps |
| Metric response | First relevant one-minute CloudWatch sample, with its period |
| Scaling response → EC2 launch | ASG Activity cause/start and new instance launch details; not an invented internal decision timestamp |
| Product startup → readiness | Existing startup log and first readiness 200 in access logs |
| Healthy → useful | Surrounding target-health snapshots, then first passing native k6 check tagged with the new instance |

**Analyse:** calculate demand-to-first-observed-useful and launch-to-useful delays, keeping polling/sample uncertainty. Use the spreadsheet for **before rise / high demand while waiting / high demand after useful capacity / reduced demand**. If clients suffer before capacity arrives, report the duration/error counts and which observed delay dominated. Improvement only after demand falls cannot be credited to scale-out alone. A successful launch is not proof that objectives held.

**Update report:** **Method** gives stage rates/durations, pilot D/W, policy units/target and timers. **Implementation** shows the policy and automatic activity cause. **Results** presents the event table and matching client windows. **Evaluation** answers whether useful capacity arrived soon enough for the chosen client objectives and what delay/capacity trade-off remained. Select that timeline for the screencast.

## Phase 6 — Test Product-instance failure and recovery

**Question → Why:** do clients continue receiving correct service when one instance disappears, and when is desired healthy capacity restored? These are separate outcomes.

**Setup:** apply failure **2/2/2**, demand scaling off, ASG replacement on. Choose a constant GET rate the one-instance pilots could handle; this tests survival with sufficient remaining capacity, not deliberate survivor overload.

**Do:**

- [ ] Start CLI state capture, then k6, and record a pre-failure window W with both instances serving correct responses.
- [ ] Note the selected instance ID and UTC time immediately before/after choosing **EC2 → Instance state → Terminate instance**. This is the experimental intervention; do not detach it, lower desired capacity, alter dependencies or apply Terraform.
- [ ] Continue for at least the pilot replacement allowance plus a post-recovery window W, within the predeclared budget. If recovery does not finish, keep the partial outcome and observation end time.

**Collect:** native k6 output, state snapshots, survivor CPU, ASG replacement activity and replacement readiness logs. Use passing checks tagged with survivor/replacement IDs to establish useful service. “Draining” means a target is being removed while existing requests may still finish; termination can produce draining/deregistration rather than a simple unhealthy state.

**Analyse:** make **before / one-survivor / restored** client windows. Compare correct throughput, p95 and errors; higher survivor CPU with deteriorating client results suggests insufficient headroom but does not alone prove overload. Calculate termination-to-replacement-start, termination-to-two-healthy and termination-to-first-observed-correct-response-on-replacement.

The snapshots bound the state transition; this minimum evidence does not establish the exact final routing attempt to the dead target. Completion samples can include requests begun before termination. Also, an EC2 termination notification can initiate ASG replacement: this experiment does not prove that ALB health-check detection caused it.

**Update report:** **Method** records the action, rate, timing bounds and definition of restored capacity. **Results** contains the three client windows and replacement milestones, including partial failure. **Evaluation** distinguishes surviving service, transition errors and restored headroom, limited to this workload and one EC2-instance loss. Do not claim a measured downtime reduction against an untested one-instance failure. Select the recovery evidence for the screencast.

## Phase 7 — Evaluate the whole architecture and answer the central question

**Question → Why:** which benefits are supported, and which shared components or delays still limit the application? Evaluation is worth 25%; supported limits are more valuable than speculative diagnosis.

**Setup:** use existing results and the deployed configuration. No new instrumentation is required to finish this phase.

**Do:** complete one short limitation table: **component/claim | Measured / Inferred / Untested possibility | evidence | consequence/uncertainty**.

| Review area | Minimum basis and allowed scope |
| --- | --- |
| Product | Paired client/CPU results, correct responses from both instances and observed errors. Say what improved at the tested demand, not an assumed maximum capacity. |
| Coupon | Functional POST check and one-instance topology. Coupon load performance is untested because measured GET bypasses it. A single required Coupon instance is an inferred failure exposure, not a measured outage duration. |
| Database | Baseline/comparison RDS CPU and connections plus the single-AZ configuration. More load/connections does not prove saturation or explain why scaling stopped helping. |
| ALB/network | Target states, client errors and configured routing/access. Without further diagnostics, leave the exact network contribution uncertain. |
| Startup and policy | Observed D, readiness/useful times, target setting and maximum two instances. Distinguish delayed launch/startup from a configured capacity ceiling. |
| Trade-offs and failure exposure | Resource counts/types, public-instance/HTTP access choice, security rules, single Coupon/RDS deployment and actual run durations. Discuss extra instance-hours/idle capacity qualitatively; no invented bills or emissions. |

**Collect:** cite existing run/configuration evidence beside each claim. Classify **Measured** only for demonstrated behaviour; **Inferred** for configuration-supported risk; **Untested possibility** for a plausible explanation without supporting observations.

**Analyse:** construct your own answer in this order: (1) quantify the scaling benefit or lack of it; (2) explain continued service and recovery during the tested failure; (3) name the workload/failure boundaries; (4) identify unchanged dependencies/limits with their classification; (5) propose **one** realistic improvement, why it deserves priority and which existing experiment would test it. You need not implement the improvement.

**Conditional diagnostics — outside the minimum path:** only add a measurement if it could change an important claim. Dependency timeouts may justify Coupon timing or database wait analysis in a new, labelled run. Unexplained connection errors may justify ALB access/error metrics. Persistent dropped k6 work may justify generator-resource monitoring. A cost-saving claim may need dated billing/rate evidence. Otherwise retain the uncertainty. Do not retrofit uncollected evidence into a conclusion.

Extra rates/repeats, a no-scaling elasticity control, a one-instance failure comparison and process-only failure are **optional**; none is needed for the bounded central answer above.

**Update report:** **Evaluation** gets that five-part answer, the classified limitations, concrete trade-offs and next improvement. Add any genuinely new observed result to **Results** before using it. Correct the architecture diagram only to reflect what was actually deployed; do not draw an unimplemented improvement as tested infrastructure.

## Phase 8 — Edit, present, submit and preserve reproducibility

**Question → Why:** can the reader verify the report's argument, and can the screencast present its strongest evidence within six minutes? The report is already written.

**Setup:** existing report, selected figures and saved native outputs; no fresh experiments unless an essential claim lacks support.

**Do:**

- [ ] Match each important claim to its run, figure/log or configuration. Recalculate quoted differences. Distinguish measured facts, inferred risks and untested possibilities.
- [ ] Ensure Method includes actual request/checks, data, rate/VUs/timeout, warm-up, duration, profiles, policy and failure action; ensure figure captions identify configuration, UTC interval, units/statistic and run.
- [ ] Check diagram/request arrows, template/build versions and Terraform profiles match the experiments. Run `terraform fmt -check` and `terraform validate`; inspect a final plan without applying during experiments. Static validation is not experimental evidence.
- [ ] Keep Results descriptive and Evaluation bounded. Confirm that references support claims actually made and that AI assistance is accurately declared.
- [ ] Use the selected architecture, paired result table and event/client timelines in the screencast. The brief's approximate allocation is 45 seconds architecture, 50 baseline, 65 scaling, 65 elasticity, 60 failure and 75 conclusion. Show AWS screens only when they substantiate a point; do not replay deployment.
- [ ] Open the final report, replay the recording, check legibility/audio/duration and submit both before the confirmed deadline. Save the receipt.
- [ ] Preserve evidence and required state/backups, then use Terraform to remove unneeded resources when no further demonstration is required. Record intentional retained resources.

**Collect → Analyse:** retain final files/receipt and check that spoken and written claims use the same values and qualifications. Editing cannot create missing evidence.

**Update report:** fix missing method parameters, captions, unsupported wording, references and the AI declaration in their existing sections. Do not begin a new report or introduce stronger conclusions at this stage.

## Review resolution and scope

This revision uses [the independent review](ca1_task_plan_review.md). “Required correction” below means a necessary fix to this plan, not a new lecturer requirement.

| Review finding | Resolution |
| --- | --- |
| **B1** — durable logs/correct-instance attribution/readiness | Phase 2 native application/access logs + CloudWatch agent; one instance-response header; phase 3 native check tags and rehearsal. No custom request-data format. |
| **B2** — transient target states | Phase 3B CLI snapshots from the student machine; all targets, actual timestamps/errors, desired versus InService versus healthy; phases 5–6 use bounded transition times. |
| **M1–M2** — construction/bootstrap ownership | Phase 2 single topology, S3 delivery, protected runtime configuration, Coupon/SSM DB initialisation, systemd, baseline apply and between-run instance refresh. |
| **M3–M5** — measurement/analysis/exports | Phase 3A–D one native k6/CloudWatch procedure, spreadsheet formulas, explicit metric windows and acquisition rehearsal. |
| **M6–M8** — policy/duration/data/repetition | Phase 5 one request-based target policy with per-minute units and pilot D/W; phases 1/3 fixed read fixtures and reset order; phase 3 two-pair rule with explicit single-pair limitation. |
| **M9–M10** — evidence scope | Each experiment has a minimum Collect list; phase 7 confines deeper diagnostics and detailed cost claims to a stated need. |
| **N1–N4** — comprehension/duplication/diagram | Actual source paths/ports/schema, first-use explanations, one collection procedure, no repeated marking paragraphs, separate ASG management arrow. |
| **O1–O2** — optional methodological improvements | Remain optional in phase 7; not prerequisites or extra mandatory experiments. |

No MAJOR finding is wholly left unresolved. The broader instrumentation mentioned under **M9/M10**—Coupon timing, DB waits, ALB access logs, generator profiling and detailed cost analysis—is deliberately **not** blanket required work. Claims needing it must either be narrowed or supported by a focused follow-up.

## Source verification

- [Official CA1 brief](../official/CA1_Cloud_Scalability_Resilience_Investigation_Brief.pdf), pp.1–5: requirements, investigations, report/screencast and marking. [Strong-grade guidance](../official/CA1_Getting_a_Strong_Grade.pdf), pp.2–8: rationale, fair tests, interpretation and communication.
- Supplied Product/Coupon controllers, entities, `application.yml` and `sql/tables.sql` under [week 3 labs](../../source/03_week/Labs/) establish the actual operations, ports, MySQL configuration and schema gap. Fix working copies only.
- Implementation references: [Terraform workflow](https://developer.hashicorp.com/terraform/cli/run), [ASG update behaviour](https://docs.aws.amazon.com/autoscaling/ec2/userguide/update-auto-scaling-group.html), [Spring Boot properties](https://docs.spring.io/spring-boot/appendix/application-properties/index.html), [Actuator readiness](https://docs.spring.io/spring-boot/reference/actuator/endpoints.html), [CloudWatch agent configuration](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch-Agent-Configuration-File-Details.html).
- Measurement references: [k6 checks/tags](https://grafana.com/docs/k6/latest/javascript-api/k6/check/), [native CSV output](https://grafana.com/docs/k6/latest/results-output/real-time/csv/), [arrival-rate executor](https://grafana.com/docs/k6/latest/using-k6/scenarios/executors/constant-arrival-rate/), [metric definitions](https://grafana.com/docs/k6/latest/using-k6/metrics/reference/), [target-health CLI](https://docs.aws.amazon.com/cli/latest/reference/elbv2/describe-target-health.html), [ALB metric statistics](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/load-balancer-cloudwatch-metrics.html), [AWS target tracking](https://docs.aws.amazon.com/autoscaling/ec2/userguide/as-scaling-target-tracking.html).
- Terraform is your additional constraint; topology, fixed GET, count choices, collection/repetition rules and sample units are planning recommendations. No deployment or performance results are claimed.
