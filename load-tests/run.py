"""Run a baseline k6 experiment and export its CloudWatch metrics."""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
WORKLOAD = Path(__file__).with_name("product.js")
EXPORTER = Path(__file__).with_name("cloudwatch.py")
REQUEST_RATE = 1
DURATION = "30s"
VUS = 2


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
    """Load the Terraform outputs needed for a baseline run."""
    outputs = json.loads(path.read_text(encoding="utf-8"))
    return {
        "alb_url": output_value(outputs, "alb_url"),
        "product_asg_name": output_value(outputs, "product_asg_name"),
        "target_group_arn": output_value(outputs, "target_group_arn"),
        "rds_identifier": output_value(outputs, "rds_identifier"),
    }


def discover_resources(infrastructure: dict[str, str]) -> dict[str, str]:
    """Find the Product instance and ALB metric dimension using AWS."""
    import boto3

    target_group_arn = infrastructure["target_group_arn"]
    arn_parts = target_group_arn.split(":", 5)
    if len(arn_parts) != 6 or arn_parts[2] != "elasticloadbalancing":
        raise ValueError("target_group_arn is not an ELB ARN")
    region = arn_parts[3]
    if not region:
        raise ValueError("target_group_arn has no AWS region")

    session = boto3.Session(region_name=region)
    asg_name = infrastructure["product_asg_name"]
    groups = session.client("autoscaling").describe_auto_scaling_groups(
        AutoScalingGroupNames=[asg_name]
    )["AutoScalingGroups"]
    if len(groups) != 1 or groups[0]["AutoScalingGroupName"] != asg_name:
        raise ValueError(f"Auto Scaling Group {asg_name!r} was not found")

    instances = [
        instance["InstanceId"] for instance in groups[0]["Instances"]
        if instance["LifecycleState"] == "InService"
    ]
    if len(instances) != 1:
        raise ValueError(
            "baseline requires one InService Product instance; "
            f"found {len(instances)}"
        )

    target_groups = session.client("elbv2").describe_target_groups(
        TargetGroupArns=[target_group_arn]
    )["TargetGroups"]
    if (
        len(target_groups) != 1
        or len(target_groups[0]["LoadBalancerArns"]) != 1
    ):
        raise ValueError("target group must belong to exactly one ALB")
    alb_arn = target_groups[0]["LoadBalancerArns"][0]
    if ":loadbalancer/app/" not in alb_arn:
        raise ValueError("target group load balancer is not an ALB")

    return {
        **infrastructure,
        "region": region,
        "product_instance_id": instances[0],
        "alb_dimension": alb_arn.split(":loadbalancer/", 1)[1],
    }


def save_metadata(directory: Path, metadata: dict[str, Any]) -> None:
    """Persist the latest run status in run.json."""
    (directory / "run.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )


def setup_experiment(
    outputs_path: Path, resources: dict[str, str],
) -> tuple[Path, dict[str, Any]]:
    """Create a unique evidence directory and its initial metadata."""
    created = utc_now()
    directory = ROOT / "evidence" / (
        f"baseline-{created.strftime('%Y%m%dT%H%M%S%fZ')}"
    )
    directory.mkdir(parents=True, exist_ok=False)
    metadata: dict[str, Any] = {
        "experiment": "baseline",
        "outputs_file": str(outputs_path.resolve()),
        "resources": resources,
        "workload": {
            "script": "load-tests/product.js",
            "rate_per_second": REQUEST_RATE,
            "duration": DURATION,
            "preallocated_vus": VUS,
        },
        "created_utc": created.isoformat(),
        "test_start_utc": None,
        "test_end_utc": None,
        "k6_exit_code": None,
        "cloudwatch_exit_code": None,
        "status": "running",
    }
    save_metadata(directory, metadata)
    return directory, metadata


def run_k6(
    directory: Path, resources: dict[str, str], metadata: dict[str, Any],
) -> bool:
    """Run k6 and save its output, UTC window and execution status."""
    command = [
        "k6", "run", "--out", f"csv={directory / 'k6.csv'}",
        "-e", f"ALB_URL={resources['alb_url']}",
        "-e", f"RATE={REQUEST_RATE}",
        "-e", f"DURATION={DURATION}",
        "-e", f"VUS={VUS}",
        str(WORKLOAD),
    ]
    try:
        with (directory / "k6.txt").open("w", encoding="utf-8") as log:
            metadata["test_start_utc"] = utc_now().isoformat()
            save_metadata(directory, metadata)
            result = subprocess.run(
                command, stdout=log, stderr=subprocess.STDOUT, check=False,
            )
            metadata["k6_exit_code"] = result.returncode
    except OSError as error:
        metadata["error"] = str(error)
    finally:
        if metadata["test_start_utc"] is not None:
            metadata["test_end_utc"] = utc_now().isoformat()
        if metadata["k6_exit_code"] != 0:
            metadata["status"] = "failed"
        save_metadata(directory, metadata)
    return metadata["k6_exit_code"] == 0


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
        "--instances", resources["product_instance_id"],
        "--alb", resources["alb_dimension"],
        "--rds", resources["rds_identifier"],
    ]
    try:
        result = subprocess.run(command, check=False)
        metadata["cloudwatch_exit_code"] = result.returncode
    except OSError as error:
        metadata["error"] = str(error)

    metadata["status"] = (
        "completed" if metadata["cloudwatch_exit_code"] == 0 else "failed"
    )
    save_metadata(directory, metadata)
    return metadata["cloudwatch_exit_code"] == 0


def main() -> int:
    """Coordinate one baseline run and report its evidence directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("experiment", choices=["baseline"])
    parser.add_argument(
        "--outputs", type=Path, default=ROOT / "infra" / "outputs.json",
        help="JSON saved from terraform output -json",
    )
    args = parser.parse_args()

    try:
        infrastructure = load_infrastructure_outputs(args.outputs)
        resources = discover_resources(infrastructure)
    except (OSError, ValueError, KeyError, TypeError, ImportError) as error:
        parser.exit(1, f"Cannot prepare baseline run: {error}\n")

    directory, metadata = setup_experiment(args.outputs, resources)
    if not run_k6(directory, resources, metadata):
        print(directory)
        return 1
    succeeded = collect_cloudwatch(directory, resources, metadata)
    print(directory)
    return 0 if succeeded else 1


if __name__ == "__main__":
    raise SystemExit(main())
