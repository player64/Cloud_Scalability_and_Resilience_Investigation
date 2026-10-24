"""Export selected CloudWatch metrics to CSV files."""

import argparse
import csv
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TypedDict


PERIOD_SECONDS = 60
POLL_TIMEOUT_SECONDS = 300
POLL_INTERVAL_SECONDS = 15
CSV_FIELDS = ("timestamp_utc", "resource_id", "metric", "statistic", "value", "unit")


class MetricDefinition(TypedDict):
    """The CloudWatch series to request and its CSV unit."""

    namespace: str
    metric: str
    dimension: str
    resource_id: str
    statistic: str
    unit: str


def parse_timestamp(value: str) -> datetime:
    """Parse an ISO 8601 timestamp that includes a timezone."""
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            f"invalid ISO 8601 timestamp: {value}"
        ) from error
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise argparse.ArgumentTypeError("timestamp must include a timezone")
    return timestamp


def parse_args() -> argparse.Namespace:
    """Parse and validate command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", required=True, help="AWS region")
    parser.add_argument(
        "--start", required=True, type=parse_timestamp,
        help="ISO 8601 start time with timezone",
    )
    parser.add_argument(
        "--end", required=True, type=parse_timestamp,
        help="ISO 8601 end time with timezone",
    )
    parser.add_argument("--output", required=True, type=Path, help="output directory")
    parser.add_argument(
        "--instances", nargs="+", metavar="INSTANCE_ID", help="EC2 instance IDs",
    )
    parser.add_argument("--alb", help="ALB LoadBalancer dimension value")
    parser.add_argument("--rds", help="RDS DB instance identifier")
    args = parser.parse_args()
    if args.end <= args.start:
        parser.error("--end must be later than --start")
    if not any((args.instances, args.alb, args.rds)):
        parser.error("supply at least one of --instances, --alb or --rds")
    return args


def metric_query(query_id: str, metric: MetricDefinition) -> dict:
    """Build a 60-second CloudWatch metric query."""
    return {
        "Id": query_id,
        "MetricStat": {
            "Metric": {
                "Namespace": metric["namespace"],
                "MetricName": metric["metric"],
                "Dimensions": [{
                    "Name": metric["dimension"],
                    "Value": metric["resource_id"],
                }],
            },
            "Period": PERIOD_SECONDS,
            "Stat": metric["statistic"],
        },
        "ReturnData": True,
    }


def requested_metrics(args: argparse.Namespace) -> dict[str, list[MetricDefinition]]:
    """Describe the requested CSV files and their metric series."""
    files = {}
    if args.instances:
        files["ec2_cpu.csv"] = [
            {
                "namespace": "AWS/EC2",
                "metric": "CPUUtilization",
                "dimension": "InstanceId",
                "resource_id": instance,
                "statistic": "Average",
                "unit": "Percent",
            }
            for instance in args.instances
        ]
    if args.alb:
        files["alb_metrics.csv"] = [
            {
                "namespace": "AWS/ApplicationELB",
                "metric": details["metric"],
                "dimension": "LoadBalancer",
                "resource_id": args.alb,
                "statistic": details["statistic"],
                "unit": details["unit"],
            }
            for details in (
                {
                    "metric": "TargetResponseTime",
                    "statistic": "Average",
                    "unit": "Seconds",
                },
                {
                    "metric": "TargetResponseTime",
                    "statistic": "p95",
                    "unit": "Seconds",
                },
                {"metric": "RequestCount", "statistic": "Sum", "unit": "Count"},
                {
                    "metric": "HTTPCode_Target_5XX_Count",
                    "statistic": "Sum",
                    "unit": "Count",
                },
            )
        ]
    if args.rds:
        files["rds_metrics.csv"] = [
            {
                "namespace": "AWS/RDS",
                "metric": "CPUUtilization",
                "dimension": "DBInstanceIdentifier",
                "resource_id": args.rds,
                "statistic": "Average",
                "unit": "Percent",
            },
            {
                "namespace": "AWS/RDS",
                "metric": "DatabaseConnections",
                "dimension": "DBInstanceIdentifier",
                "resource_id": args.rds,
                "statistic": "Average",
                "unit": "Count",
            },
        ]
    return files


def rows_from_response(
    response: dict, metrics_by_id: dict[str, MetricDefinition],
) -> list[dict]:
    """Validate a CloudWatch page and convert its datapoints to CSV rows."""
    rows = []
    for result in response["MetricDataResults"]:
        status = result.get("StatusCode")
        if status not in ("Complete", "PartialData"):
            raise RuntimeError(
                f"CloudWatch returned {status} for query {result['Id']}"
            )
        if status == "PartialData" and not response.get("NextToken"):
            raise RuntimeError(
                f"CloudWatch returned incomplete data for query {result['Id']}"
            )

        metric = metrics_by_id[result["Id"]]
        if len(result["Timestamps"]) != len(result["Values"]):
            raise RuntimeError(f"CloudWatch returned mismatched datapoints for {result['Id']}")
        for timestamp, value in zip(result["Timestamps"], result["Values"]):
            rows.append({
                "timestamp_utc": timestamp.astimezone(timezone.utc).isoformat(),
                "resource_id": metric["resource_id"],
                "metric": metric["metric"],
                "statistic": metric["statistic"],
                "value": value,
                "unit": metric["unit"],
            })
    return rows


def fetch_metrics(
    client, definitions: list[MetricDefinition], start: datetime, end: datetime,
) -> list[dict]:
    """Fetch and sort all pages of the requested metric series."""
    rows = []
    start = start.astimezone(timezone.utc).replace(second=0, microsecond=0)
    # EndTime is exclusive; include the bucket containing the actual end.
    end = end.astimezone(timezone.utc).replace(second=0, microsecond=0) + timedelta(minutes=1)
    # GetMetricData accepts at most 500 queries per request.
    for offset in range(0, len(definitions), 500):
        batch = definitions[offset:offset + 500]
        metrics_by_id = {
            f"m{index}": metric for index, metric in enumerate(batch)
        }
        request = {
            "MetricDataQueries": [
                metric_query(query_id, metric)
                for query_id, metric in metrics_by_id.items()
            ],
            "StartTime": start,
            "EndTime": end,
            "ScanBy": "TimestampAscending",
        }

        response = client.get_metric_data(**request)
        seen = set()
        seen.update(result["Id"] for result in response.get("MetricDataResults", []))
        rows.extend(rows_from_response(response, metrics_by_id))
        next_token = response.get("NextToken")
        while next_token:
            response = client.get_metric_data(**request, NextToken=next_token)
            seen.update(result["Id"] for result in response.get("MetricDataResults", []))
            rows.extend(rows_from_response(response, metrics_by_id))
            next_token = response.get("NextToken")
        if seen != metrics_by_id.keys():
            raise RuntimeError(f"CloudWatch omitted metric results: {metrics_by_id.keys() - seen}")

    return sorted(
        rows,
        key=lambda row: (
            row["timestamp_utc"], row["resource_id"],
            row["metric"], row["statistic"],
        ),
    )


def derived_alb_rows(rows: list[dict]) -> list[dict]:
    """Calculate throughput and target 5xx percentage from ALB counts."""
    requests = {}
    target_errors = {}
    derived = []

    for row in rows:
        key = (row["timestamp_utc"], row["resource_id"])
        if row["metric"] == "RequestCount" and row["statistic"] == "Sum":
            requests[key] = row["value"]
            derived.append({
                "timestamp_utc": row["timestamp_utc"],
                "resource_id": row["resource_id"],
                "metric": "Throughput",
                "statistic": "Derived",
                "value": row["value"] / PERIOD_SECONDS,
                "unit": "Requests/Second",
            })
        elif row["metric"] == "HTTPCode_Target_5XX_Count" and row["statistic"] == "Sum":
            target_errors[key] = row["value"]

    for key, request_count in requests.items():
        if request_count <= 0 or key not in target_errors:
            continue
        timestamp, resource_id = key
        derived.append({
            "timestamp_utc": timestamp,
            "resource_id": resource_id,
            "metric": "Target5XXErrorRate",
            "statistic": "Derived",
            "value": 100 * target_errors[key] / request_count,
            "unit": "Percent",
        })

    return derived


def write_csv(path: Path, rows: list[dict]) -> None:
    """Write metric rows without replacing an existing file."""
    with path.open("x", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def export(client, files: dict[str, list[MetricDefinition]],
           start: datetime, end: datetime, output: Path) -> dict[str, list[dict]]:
    """Poll for active ALB request periods and retain partial CSVs on failure."""
    expected = set()
    period = start.astimezone(timezone.utc).replace(second=0, microsecond=0)
    last = end.astimezone(timezone.utc).replace(second=0, microsecond=0)
    while period <= last:
        expected.add(period.isoformat())
        period += timedelta(seconds=PERIOD_SECONDS)

    collected = {name: {} for name in files}
    deadline = time.monotonic() + POLL_TIMEOUT_SECONDS
    output.mkdir(parents=True, exist_ok=True)
    try:
        while True:
            for name, definitions in files.items():
                if name != "alb_metrics.csv" and collected[name]:
                    continue
                for row in fetch_metrics(client, definitions, start, end):
                    key = (row["timestamp_utc"], row["resource_id"],
                           row["metric"], row["statistic"])
                    collected[name][key] = row
            request_periods = {
                row["timestamp_utc"] for row in collected.get("alb_metrics.csv", {}).values()
                if row["metric"] == "RequestCount" and row["statistic"] == "Sum"
            }
            missing_periods = expected - request_periods if "alb_metrics.csv" in files else set()
            missing_files = [name for name, rows in collected.items() if not rows]
            # The final aggregate cannot be considered settled before its minute ends.
            final_period_end = last + timedelta(seconds=PERIOD_SECONDS)
            if (not missing_periods and not missing_files
                    and datetime.now(timezone.utc) >= final_period_end):
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError(
                    "CloudWatch evidence incomplete; missing files: "
                    f"{', '.join(missing_files)}; missing ALB RequestCount periods: "
                    f"{', '.join(sorted(missing_periods))}"
                )
            time.sleep(min(POLL_INTERVAL_SECONDS, remaining))
    finally:
        results = {}
        for name, unique in collected.items():
            rows = sorted(unique.values(), key=lambda row: (
                row["timestamp_utc"], row["resource_id"],
                row["metric"], row["statistic"],
            ))
            if name == "alb_metrics.csv":
                rows = sorted(rows + derived_alb_rows(rows), key=lambda row: (
                    row["timestamp_utc"], row["resource_id"],
                    row["metric"], row["statistic"],
                ))
            write_csv(output / name, rows)
            results[name] = rows
    return results


def main() -> int:
    """Fetch requested metrics and write their CSV files."""
    args = parse_args()
    files = requested_metrics(args)
    existing = [name for name in files if (args.output / name).exists()]
    if existing:
        raise SystemExit(f"output file already exists: {', '.join(existing)}")

    try:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError
    except ImportError as error:
        raise SystemExit(
            "boto3 is required; install it with python3 -m pip install boto3"
        ) from error

    client = boto3.client("cloudwatch", region_name=args.region)
    try:
        export(client, files, args.start, args.end, args.output)
    except (BotoCoreError, ClientError) as error:
        raise SystemExit(f"CloudWatch request failed: {error}") from error
    except RuntimeError as error:
        raise SystemExit(str(error)) from error
    except OSError as error:
        raise SystemExit(f"could not write CSV files: {error}") from error

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
