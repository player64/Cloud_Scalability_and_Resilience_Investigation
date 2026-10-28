"""Run a Product experiment and export its CloudWatch metrics."""

import argparse
import csv
import json
import re
import shutil
import subprocess
import sys
import time
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from experiments import EXPERIMENTS
from observe import Observer


ROOT = Path(__file__).resolve().parent.parent
WORKLOAD = Path(__file__).with_name("product.js")
RAMP_WORKLOAD = Path(__file__).with_name("product-ramp.js")
EXPORTER = Path(__file__).with_name("cloudwatch.py")
REQUEST_RATE = 1
DURATION = "30s"
VUS = 2
RECONCILE_TIMEOUT = 300
RECONCILE_DELAY = 15


def positive_integer(value: str) -> int:
    """Parse a positive whole-number CLI value."""
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a positive integer") from error
    if number <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def k6_duration(value: str) -> str:
    """Accept a positive k6 duration in seconds, minutes or hours."""
    if not re.fullmatch(r"[1-9][0-9]*(?:s|m|h)", value):
        raise argparse.ArgumentTypeError("must be a positive duration such as 30s, 5m or 1h")
    return value


def utc_now() -> datetime:
    """Return the current time in UTC."""
    return datetime.now(timezone.utc)


def output_value(outputs: dict[str, Any], name: str) -> str:
    """Read one string value from Terraform's JSON output format."""
    try:
        value = outputs[name]["value"]
    except (KeyError, TypeError) as error:
        raise ValueError(f"Terraform output {name!r} is missing") from error
    if not isinstance(value, str) or not value:
        raise ValueError(
            f"Terraform output {name!r} must be a non-empty string"
        )
    return value


def load_infrastructure_outputs(path: Path) -> dict[str, str]:
    """Load current infrastructure references and its applied profile label."""
    outputs = json.loads(path.read_text(encoding="utf-8"))
    return {
        "alb_url": output_value(outputs, "alb_url"),
        "product_asg_name": output_value(outputs, "product_asg_name"),
        "target_group_arn": output_value(outputs, "target_group_arn"),
        "rds_identifier": output_value(outputs, "rds_identifier"),
        "experiment_profile": output_value(outputs, "experiment_profile"),
        "evidence_bucket": output_value(outputs, "evidence_bucket"),
    }


def discover_resources(infrastructure: dict[str, str], experiment: str = "baseline") -> dict:
    """Find Product members and check target health without inferring a profile."""
    import boto3

    target_group_arn = infrastructure["target_group_arn"]
    arn_parts = target_group_arn.split(":", 5)
    if len(arn_parts) != 6 or arn_parts[2] != "elasticloadbalancing" or not arn_parts[3]:
        raise ValueError("target_group_arn is not a regional ELB ARN")
    region = arn_parts[3]
    session = boto3.Session(region_name=region)
    asg_name = infrastructure["product_asg_name"]
    groups = session.client("autoscaling").describe_auto_scaling_groups(
        AutoScalingGroupNames=[asg_name])["AutoScalingGroups"]
    if len(groups) != 1 or groups[0]["AutoScalingGroupName"] != asg_name:
        raise ValueError(f"Auto Scaling Group {asg_name!r} was not found")
    instances = [item["InstanceId"] for item in groups[0]["Instances"]
                 if item["LifecycleState"] == "InService"]
    expected = EXPERIMENTS[experiment]["members"]
    if len(instances) != expected:
        raise ValueError(f"{experiment} requires {expected} InService Product instance(s); "
                         f"found {len(instances)}")

    elbv2 = session.client("elbv2")
    target_groups = elbv2.describe_target_groups(
        TargetGroupArns=[target_group_arn])["TargetGroups"]
    if len(target_groups) != 1 or len(target_groups[0]["LoadBalancerArns"]) != 1:
        raise ValueError("target group must belong to exactly one ALB")
    alb_arn = target_groups[0]["LoadBalancerArns"][0]
    if ":loadbalancer/app/" not in alb_arn:
        raise ValueError("target group load balancer is not an ALB")

    result = {**infrastructure, "region": region,
              "product_instance_id": instances[0],
              "alb_dimension": alb_arn.split(":loadbalancer/", 1)[1]}
    if experiment != "baseline":
        health = elbv2.describe_target_health(
            TargetGroupArn=target_group_arn)["TargetHealthDescriptions"]
        healthy = {item["Target"]["Id"] for item in health
                   if item["TargetHealth"]["State"] == "healthy"}
        if healthy != set(instances):
            raise ValueError(f"{experiment} requires {expected} healthy InService targets; "
                             f"found {len(healthy & set(instances))}")
        result["product_instance_ids"] = sorted(instances)
    return result


def save_metadata(directory: Path, metadata: dict[str, Any]) -> None:
    """Persist the latest run status in run.json."""
    (directory / "run.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )


def upload_evidence(directory: Path, metadata: dict[str, Any], bucket: str,
                    region: str) -> None:
    """Upload every available run file, including partial evidence on failure."""
    import boto3

    metadata["evidence_upload"] = {"status": "running", "error": None}
    save_metadata(directory, metadata)
    client = boto3.client("s3", region_name=region)
    prefix = f"evidence/{directory.name}/"
    for path in sorted(directory.rglob("*")):
        if path.is_file() and path != directory / "run.json":
            client.upload_file(str(path), bucket,
                               prefix + path.relative_to(directory).as_posix())
    metadata["evidence_upload"]["status"] = "completed"
    save_metadata(directory, metadata)
    client.upload_file(str(directory / "run.json"), bucket, prefix + "run.json")


def evidence_rows(path: Path, required: set[str]) -> bool:
    """Require a readable CSV with its schema and at least one measurement."""
    try:
        with path.open(newline="", encoding="utf-8") as source:
            reader = csv.DictReader(source)
            return required.issubset(reader.fieldnames or []) and any(
                all(row.get(field) for field in required) for row in reader
            )
    except (OSError, csv.Error, UnicodeError):
        return False


def valid_k6_evidence(path: Path) -> bool:
    """Require request samples and a passing response check."""
    try:
        with path.open(newline="", encoding="utf-8") as source:
            reader = csv.DictReader(source)
            if not {"metric_name", "timestamp", "metric_value"}.issubset(reader.fieldnames or []):
                return False
            metrics = {row["metric_name"] for row in reader
                       if row.get("timestamp") and row.get("metric_value")}
            return {"checks", "http_req_duration"}.issubset(metrics)
    except (OSError, csv.Error, UnicodeError, KeyError):
        return False


def k6_request_count(path: Path) -> int | None:
    """Sum native k6 http_reqs counter samples, independently of iterations."""
    try:
        with path.open(newline="", encoding="utf-8") as source:
            reader = csv.DictReader(source)
            if not {"metric_name", "metric_value"}.issubset(reader.fieldnames or []):
                return None
            values = [Decimal(row["metric_value"]) for row in reader
                      if row.get("metric_name") == "http_reqs"]
        total = sum(values)
        return int(total) if values and total >= 0 and total == int(total) else None
    except (OSError, csv.Error, UnicodeError, InvalidOperation, ValueError, TypeError):
        return None


def alb_request_count(path: Path, resource_id: str) -> int | None:
    """Sum the selected ALB's RequestCount Sum datapoints only."""
    try:
        with path.open(newline="", encoding="utf-8") as source:
            reader = csv.DictReader(source)
            if not {"resource_id", "metric", "statistic", "value"}.issubset(reader.fieldnames or []):
                return None
            values = [Decimal(row["value"]) for row in reader
                      if row.get("resource_id") == resource_id
                      and row.get("metric") == "RequestCount"
                      and row.get("statistic") == "Sum"]
        total = sum(values)
        return int(total) if values and total >= 0 and total == int(total) else None
    except (OSError, csv.Error, UnicodeError, InvalidOperation, ValueError, TypeError):
        return None


def valid_alb_evidence(path: Path, start: str, end: str) -> bool:
    """Require ALB request counts for every overlapping minute."""
    period = datetime.fromisoformat(start).astimezone(timezone.utc).replace(second=0, microsecond=0)
    last = datetime.fromisoformat(end).astimezone(timezone.utc).replace(second=0, microsecond=0)
    expected = set()
    while period <= last:
        expected.add(period.isoformat())
        period += timedelta(minutes=1)
    try:
        with path.open(newline="", encoding="utf-8") as source:
            reader = csv.DictReader(source)
            if not {"timestamp_utc", "resource_id", "metric", "statistic", "value", "unit"}.issubset(
                reader.fieldnames or []
            ):
                return False
            observed = {row["timestamp_utc"] for row in reader
                        if row.get("metric") == "RequestCount"
                        and row.get("statistic") == "Sum" and row.get("value")}
            return expected.issubset(observed)
    except (OSError, csv.Error, UnicodeError):
        return False


def setup_experiment(
    outputs_path: Path, resources: dict[str, str],
    rate: int = REQUEST_RATE, duration: str = DURATION, vus: int = VUS,
    experiment: str = "baseline", ramp: dict | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Create a unique evidence directory and its initial metadata."""
    created = utc_now()
    directory = ROOT / "evidence" / (
        f"{experiment}-{created.strftime('%Y%m%dT%H%M%S%fZ')}"
    )
    directory.mkdir(parents=True, exist_ok=False)
    metadata: dict[str, Any] = {
        "experiment": experiment,
        "outputs_file": str(outputs_path.resolve()),
        "resources": resources,
        "workload": {
            "script": "load-tests/product.js",
            "rate_per_second": rate,
            "duration": duration,
            "preallocated_vus": vus,
        },
        "created_utc": created.isoformat(),
        "test_start_utc": None,
        "test_end_utc": None,
        "k6_exit_code": None,
        "cloudwatch_exit_code": None,
        "workload_error": None,
        "cloudwatch_error": None,
        "reconciliation": {"status": "pending", "k6_requests": None,
                           "alb_requests": None, "difference": None, "attempts": 0},
        "status": "running",
    }
    metadata["provisioned_profile"] = resources["experiment_profile"]
    if experiment != "baseline":
        metadata["initial_instance_ids"] = resources["product_instance_ids"]
        metadata["observation"] = {"status": "pending", "samples": 0,
                                   "errors": 0, "instance_ids": []}
    if ramp is not None:
        metadata["workload"]["ramp"] = ramp
        metadata["workload"]["script"] = "load-tests/product-ramp.js"
    save_metadata(directory, metadata)
    return directory, metadata


def run_k6(
    directory: Path, resources: dict[str, str], metadata: dict[str, Any],
) -> bool:
    """Run k6 and save its output, UTC window and execution status."""
    workload = metadata["workload"]
    command = ["k6", "run", "--out", f"csv={directory / 'k6.csv'}"]
    if "ramp" in workload:
        ramp = workload["ramp"]
        command.extend(["-e", f"ALB_URL={resources['alb_url']}",
                        "-e", f"VUS={workload['preallocated_vus']}"])
        command.extend([item for key, value in (
            ("LOW_RATE", ramp["low_rate_per_second"]),
            ("HIGH_RATE", workload["rate_per_second"]),
            ("PRE_DURATION", ramp["pre_duration"]),
            ("RISE_DURATION", ramp["rise_duration"]),
            ("HIGH_DURATION", workload["duration"]),
            ("FALL_DURATION", ramp["fall_duration"]),
            ("POST_DURATION", ramp["post_duration"]),
        ) for item in ("-e", f"{key}={value}")])
        command.append(str(RAMP_WORKLOAD))
    else:
        # Preserve the original baseline command and its environment ordering.
        command.extend([
            "-e", f"ALB_URL={resources['alb_url']}",
            "-e", f"RATE={workload['rate_per_second']}",
            "-e", f"DURATION={workload['duration']}",
            "-e", f"VUS={workload['preallocated_vus']}", str(WORKLOAD),
        ])
    metadata["k6_command"] = command
    metadata["k6_environment"] = {
        "ALB_URL": resources["alb_url"],
        "RATE": str(workload["rate_per_second"]),
        "DURATION": workload["duration"],
        "VUS": str(workload["preallocated_vus"]),
    }
    if "ramp" in workload:
        metadata["k6_environment"] = {
            "ALB_URL": resources["alb_url"], "VUS": str(workload["preallocated_vus"]),
            "LOW_RATE": str(ramp["low_rate_per_second"]),
            "HIGH_RATE": str(workload["rate_per_second"]),
            "PRE_DURATION": ramp["pre_duration"], "RISE_DURATION": ramp["rise_duration"],
            "HIGH_DURATION": workload["duration"], "FALL_DURATION": ramp["fall_duration"],
            "POST_DURATION": ramp["post_duration"],
        }
    try:
        with (directory / "k6.txt").open("w", encoding="utf-8") as log:
            metadata["test_start_utc"] = utc_now().isoformat()
            save_metadata(directory, metadata)
            result = subprocess.run(
                command, stdout=log, stderr=subprocess.STDOUT, check=False,
            )
            metadata["k6_exit_code"] = result.returncode
    except Exception as error:
        metadata["workload_error"] = f"k6 execution failed: {error}"
    finally:
        if metadata["test_start_utc"] is not None:
            metadata["test_end_utc"] = utc_now().isoformat()
        if metadata["k6_exit_code"] not in (None, 0):
            metadata["workload_error"] = f"k6 exited with code {metadata['k6_exit_code']}"
        if not valid_k6_evidence(directory / "k6.csv"):
            reason = "k6 CSV has no valid measurements"
            metadata["workload_error"] = (
                f"{metadata['workload_error']}; {reason}"
                if metadata["workload_error"] else reason
            )
        if metadata["k6_exit_code"] != 0 or metadata["workload_error"]:
            metadata["status"] = "failed"
        save_metadata(directory, metadata)
    return metadata["k6_exit_code"] == 0 and not metadata["workload_error"]


def collect_cloudwatch(
    directory: Path, resources: dict[str, str], metadata: dict[str, Any],
) -> bool:
    """Export CloudWatch metrics for the recorded k6 window."""
    command = [
        sys.executable, str(EXPORTER),
        "--region", resources["region"],
        "--start", metadata["test_start_utc"],
        "--end", metadata["test_end_utc"],
        "--output", str(directory),
        "--instances", *resources.get("product_instance_ids", [resources["product_instance_id"]]),
        "--alb", resources["alb_dimension"],
        "--rds", resources["rds_identifier"],
    ]
    if metadata.get("experiment", "baseline") != "baseline":
        command.append("--event-metrics")
    try:
        with (directory / "cloudwatch.txt").open("w", encoding="utf-8") as log:
            result = subprocess.run(
                command, stdout=log, stderr=subprocess.STDOUT, check=False,
            )
            metadata["cloudwatch_exit_code"] = result.returncode
    except Exception as error:
        metadata["cloudwatch_error"] = f"CloudWatch export failed: {error}"

    expected = ("ec2_cpu.csv", "alb_metrics.csv", "rds_metrics.csv")
    missing = [
        name for name in expected
        if not evidence_rows(directory / name,
                             {"timestamp_utc", "resource_id", "metric", "statistic", "value", "unit"})
    ]
    if not valid_alb_evidence(directory / "alb_metrics.csv",
                              metadata["test_start_utc"], metadata["test_end_utc"]):
        missing.append("ALB RequestCount periods")
    complete = metadata["cloudwatch_exit_code"] == 0 and not missing
    if metadata["cloudwatch_exit_code"] not in (None, 0):
        metadata["cloudwatch_error"] = (
            f"CloudWatch export exited with code {metadata['cloudwatch_exit_code']}"
        )
    if missing:
        reason = f"CloudWatch evidence missing or incomplete: {', '.join(missing)}"
        metadata["cloudwatch_error"] = (
            f"{metadata['cloudwatch_error']}; {reason}"
            if metadata.get("cloudwatch_error") else reason
        )
    metadata["status"] = "running" if complete and metadata["status"] != "failed" else "failed"
    save_metadata(directory, metadata)
    return complete


def reconcile_requests(directory: Path, resources: dict[str, str],
                       metadata: dict[str, Any], cloudwatch_complete: bool,
                       timeout: int, delay: int) -> None:
    """Refresh only ALB evidence until request totals agree or time runs out."""
    result = metadata["reconciliation"]
    result["attempts"] = 1
    result["k6_requests"] = k6_request_count(directory / "k6.csv")
    if result["k6_requests"] is None:
        result["status"] = "unavailable"
    if not cloudwatch_complete:
        result["status"] = "unavailable"
        metadata["status"] = "failed"
        save_metadata(directory, metadata)
        return

    deadline = time.monotonic() + timeout
    while True:
        result["alb_requests"] = alb_request_count(
            directory / "alb_metrics.csv", resources["alb_dimension"]
        )
        if result["k6_requests"] is not None and result["alb_requests"] is not None:
            result["difference"] = result["alb_requests"] - result["k6_requests"]
            if result["difference"] == 0:
                result["status"] = "matched"
                break
            if result["difference"] > 0:
                result["status"] = "mismatch"
                result["reason"] = (
                    "ALB counted more requests than k6; check other traffic and "
                    "the overlapping first/last CloudWatch minute buckets"
                )
                break
        if result["k6_requests"] is None:
            break
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            result["status"] = "timeout"
            break
        time.sleep(min(delay, remaining))
        if time.monotonic() >= deadline:
            result["status"] = "timeout"
            break

        result["attempts"] += 1
        attempts_dir = directory / "reconciliation"
        attempt_dir = attempts_dir / f"attempt_{result['attempts']}"
        try:
            attempts_dir.mkdir(exist_ok=True)
            if result["attempts"] == 2:
                shutil.copy2(directory / "alb_metrics.csv", attempts_dir / "alb_metrics_attempt_1.csv")
            attempt_dir.mkdir(exist_ok=False)
            command = [
                sys.executable, str(EXPORTER), "--region", resources["region"],
                "--start", metadata["test_start_utc"],
                "--end", metadata["test_end_utc"],
                "--output", str(attempt_dir), "--alb", resources["alb_dimension"],
            ]
            with (attempt_dir / "cloudwatch.txt").open("w", encoding="utf-8") as log:
                export = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT,
                                        check=False, timeout=max(0.001, deadline - time.monotonic()))
            if export.returncode != 0:
                metadata["cloudwatch_error"] = (
                    f"ALB refresh exited with code {export.returncode}; "
                    f"see {attempt_dir / 'cloudwatch.txt'}"
                )
                result["status"] = "unavailable"
                break
            refreshed = attempt_dir / "alb_metrics.csv"
            if not valid_alb_evidence(refreshed, metadata["test_start_utc"],
                                      metadata["test_end_utc"]):
                metadata["cloudwatch_error"] = f"ALB refresh has incomplete periods: {refreshed}"
                result["status"] = "unavailable"
                break
            shutil.copy2(refreshed, directory / "alb_metrics.csv")
        except subprocess.TimeoutExpired as error:
            metadata["cloudwatch_error"] = f"ALB refresh timed out: {error}"
            result["status"] = "timeout"
            break
        except OSError as error:
            metadata["cloudwatch_error"] = f"ALB refresh failed: {error}"
            result["status"] = "unavailable"
            break

    if result["status"] == "timeout" and not metadata["cloudwatch_error"]:
        result["reason"] = "ALB RequestCount did not reconcile before timeout"
    metadata["status"] = (
        "completed" if result["status"] == "matched"
        and metadata["k6_exit_code"] == 0 and not metadata["workload_error"]
        and not metadata["cloudwatch_error"] else "failed"
    )
    save_metadata(directory, metadata)


def execute_experiment(args: argparse.Namespace, resources: dict[str, str],
                       directory: Path, metadata: dict[str, Any],
                       experiment: str) -> int:
    """Run a prepared experiment, leaving its local evidence intact."""
    observer = None
    if experiment != "baseline":
        try:
            import boto3
            observer = Observer(boto3.Session(region_name=resources["region"]),
                                resources["product_asg_name"], resources["target_group_arn"],
                                directory / "aws_observations.jsonl", args.observe_interval)
            observer.start()
        except Exception as error:
            metadata["status"] = "failed"
            metadata["observation"] = {"status": "start_failed", "error": str(error),
                                       "samples": 0, "errors": 0, "instance_ids": []}
            save_metadata(directory, metadata)
            print(f"AWS observation could not start: {type(error).__name__}; evidence: {directory}")
            return 1
        if experiment == "failure":
            print("Failure injection is manual. Record action start/end UTC times and the selected "
                  "instance ID in this evidence directory; the runner never terminates an instance.",
                  flush=True)
    try:
        k6_succeeded = run_k6(directory, resources, metadata)
    finally:
        if observer is not None:
            stopped = observer.stop()
            metadata["observation"] = {
                "status": "completed" if stopped and observer.samples and not observer.errors
                          else "partial",
                "samples": observer.samples, "errors": observer.errors,
                "instance_ids": sorted(observer.seen_ids),
            }
            resources["product_instance_ids"] = sorted(
                set(resources["product_instance_ids"]) | observer.seen_ids)
            save_metadata(directory, metadata)
    if (metadata["test_start_utc"] and metadata["test_end_utc"]
            and datetime.fromisoformat(metadata["test_end_utc"])
            > datetime.fromisoformat(metadata["test_start_utc"])):
        cloudwatch_complete = collect_cloudwatch(directory, resources, metadata)
        if k6_succeeded or experiment != "baseline":
            reconcile_requests(directory, resources, metadata, cloudwatch_complete,
                               args.reconcile_timeout, args.reconcile_delay)
        else:
            metadata["reconciliation"]["status"] = "skipped"
            metadata["reconciliation"]["reason"] = "k6 execution was unsuccessful"
            metadata["status"] = "failed"
            save_metadata(directory, metadata)
    else:
        metadata["cloudwatch_error"] = "CloudWatch export skipped: valid test timestamps unavailable"
        metadata["status"] = "failed"
        metadata["reconciliation"]["status"] = "unavailable"
        save_metadata(directory, metadata)

    if observer is not None and metadata["observation"]["status"] != "completed":
        metadata["status"] = "failed"
        save_metadata(directory, metadata)

    workload = metadata["workload"]
    print(f"Experiment: {metadata['experiment']} | {workload['rate_per_second']} req/s | "
          f"{workload['duration']} | {workload['preallocated_vus']} VUs")
    k6_detail = f" ({metadata['workload_error']})" if metadata["workload_error"] else ""
    cloudwatch_detail = (
        f" ({metadata['cloudwatch_error']})" if metadata["cloudwatch_error"] else ""
    )
    print(f"k6: exit {metadata['k6_exit_code']}{k6_detail}")
    print(f"CloudWatch: exit {metadata['cloudwatch_exit_code']}{cloudwatch_detail}")
    reconciliation = metadata["reconciliation"]
    print(f"ALB reconciliation: {reconciliation['status']} "
          f"(difference: {reconciliation['difference']}); "
          f"{reconciliation.get('reason', '')}")
    print(f"Status: {metadata['status']}")
    print(f"Evidence: {directory}")
    return 0 if metadata["status"] == "completed" else 1


def main() -> int:
    """Coordinate a student-run trial and upload its evidence directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rate", type=positive_integer, default=REQUEST_RATE,
                        help="requests per second (default: 1)")
    parser.add_argument("--duration", type=k6_duration, default=DURATION,
                        help="k6 duration, e.g. 30s or 5m (default: 30s)")
    parser.add_argument("--vus", type=positive_integer, default=VUS,
                         help="preallocated virtual users (default: 2)")
    parser.add_argument("--low-rate", type=positive_integer,
                        help="elasticity low-stage iterations per second")
    for option in ("pre-duration", "rise-duration", "fall-duration", "post-duration"):
        parser.add_argument(f"--{option}", type=k6_duration,
                            help="elasticity stage duration")
    parser.add_argument("--observe-interval", type=positive_integer, default=15,
                        help="event snapshot interval in seconds (default: 15)")
    parser.add_argument("--reconcile-timeout", type=positive_integer,
                        default=RECONCILE_TIMEOUT, help="ALB reconciliation timeout in seconds")
    parser.add_argument("--reconcile-delay", type=positive_integer,
                        default=RECONCILE_DELAY, help="seconds between ALB refresh attempts")
    parser.add_argument(
        "--outputs", type=Path, default=ROOT / "infra" / "outputs.json",
        help="JSON saved from terraform output -json",
    )
    args = parser.parse_args()
    try:
        infrastructure = load_infrastructure_outputs(args.outputs)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        parser.exit(1, f"Cannot read infrastructure outputs: {error}\n")
    experiment = infrastructure["experiment_profile"]
    if experiment not in EXPERIMENTS:
        parser.exit(1, f"Unsupported experiment_profile {experiment!r} in {args.outputs}\n")

    ramp_names = ("low_rate", "pre_duration", "rise_duration", "fall_duration", "post_duration")
    if experiment == "elasticity" and any(getattr(args, key) is None for key in ramp_names):
        parser.error("elasticity requires --low-rate and all four stage-duration options")
    if experiment != "elasticity" and any(getattr(args, key) is not None for key in ramp_names):
        parser.error("ramp options are available only for elasticity")
    ramp = ({"low_rate_per_second": args.low_rate, "pre_duration": args.pre_duration,
             "rise_duration": args.rise_duration, "fall_duration": args.fall_duration,
             "post_duration": args.post_duration} if experiment == "elasticity" else None)

    try:
        resources = discover_resources(infrastructure, experiment)
    except (OSError, ValueError, KeyError, TypeError, ImportError) as error:
        parser.exit(1, f"Cannot prepare {experiment} run: {error}\n")

    directory, metadata = setup_experiment(
        args.outputs, resources, args.rate, args.duration, args.vus,
        experiment, ramp,
    )
    try:
        result = execute_experiment(args, resources, directory, metadata, experiment)
    except KeyboardInterrupt:
        metadata["status"] = "failed"
        metadata["runner_error"] = "Interrupted by operator"
        save_metadata(directory, metadata)
        result = 130
    except Exception as error:
        metadata["status"] = "failed"
        metadata["runner_error"] = f"{type(error).__name__}: {error}"
        save_metadata(directory, metadata)
        print(f"Experiment failed: {type(error).__name__}; evidence: {directory}")
        result = 1
    finally:
        try:
            upload_evidence(directory, metadata, infrastructure["evidence_bucket"],
                            resources["region"])
            print(f"Evidence uploaded: s3://{infrastructure['evidence_bucket']}/evidence/{directory.name}/")
        except Exception as error:
            metadata["evidence_upload"] = {
                "status": "failed", "error": f"{type(error).__name__}: {error}",
            }
            save_metadata(directory, metadata)
            print(f"Evidence upload failed: {type(error).__name__}; local evidence: {directory}")
            result = 1
    return result


if __name__ == "__main__":
    raise SystemExit(main())
