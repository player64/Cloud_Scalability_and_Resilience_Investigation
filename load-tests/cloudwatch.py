"""Export selected CloudWatch metrics to CSV files."""

import argparse
import csv
from datetime import datetime, timezone
from pathlib import Path


PERIOD_SECONDS = 60
CSV_FIELDS = ("timestamp_utc", "resource_id", "metric", "statistic", "value", "unit")


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


def metric_query(
    query_id: str, namespace: str, metric: str, dimension: str,
    resource_id: str, statistic: str,
) -> dict:
    """Build a 60-second CloudWatch metric query."""
    return {
        "Id": query_id,
        "MetricStat": {
            "Metric": {
                "Namespace": namespace,
                "MetricName": metric,
                "Dimensions": [{"Name": dimension, "Value": resource_id}],
            },
            "Period": PERIOD_SECONDS,
            "Stat": statistic,
        },
        "ReturnData": True,
    }


def requested_metrics(args: argparse.Namespace) -> dict[str, list[tuple]]:
    """Describe the requested CSV files and their metric series."""
    files = {}
    if args.instances:
        files["ec2_cpu.csv"] = [
            ("AWS/EC2", "CPUUtilization", "InstanceId", instance, "Average", "Percent")
            for instance in args.instances
        ]
    if args.alb:
        files["alb_metrics.csv"] = [
            ("AWS/ApplicationELB", metric, "LoadBalancer", args.alb, statistic, unit)
            for metric, statistic, unit in (
                ("TargetResponseTime", "Average", "Seconds"),
                ("TargetResponseTime", "p95", "Seconds"),
                ("RequestCount", "Sum", "Count"),
                ("HTTPCode_Target_5XX_Count", "Sum", "Count"),
            )
        ]
    if args.rds:
        files["rds_metrics.csv"] = [
            (
                "AWS/RDS", "CPUUtilization", "DBInstanceIdentifier",
                args.rds, "Average", "Percent",
            ),
            (
                "AWS/RDS", "DatabaseConnections", "DBInstanceIdentifier",
                args.rds, "Average", "Count",
            ),
        ]
    return files


def fetch_metrics(
    client, definitions: list[tuple], start: datetime, end: datetime,
) -> list[dict]:
    """Fetch all pages of the requested metric series."""
    rows = []
    for offset in range(0, len(definitions), 500):
        batch = definitions[offset:offset + 500]
        queries = [
            metric_query(f"m{index}", *definition[:5])
            for index, definition in enumerate(batch)
        ]
        next_token = None
        while True:
            request = {
                "MetricDataQueries": queries,
                "StartTime": start,
                "EndTime": end,
                "ScanBy": "TimestampAscending",
            }
            if next_token:
                request["NextToken"] = next_token
            response = client.get_metric_data(**request)
            for result in response["MetricDataResults"]:
                status = result.get("StatusCode")
                if status not in (None, "Complete", "PartialData"):
                    raise RuntimeError(
                        f"CloudWatch returned {status} "
                        f"for query {result['Id']}"
                    )
                if status == "PartialData" and not response.get("NextToken"):
                    raise RuntimeError(
                        f"CloudWatch returned incomplete data for query {result['Id']}"
                    )
                definition = batch[int(result["Id"][1:])]
                for timestamp, value in zip(result["Timestamps"], result["Values"]):
                    rows.append({
                        "timestamp_utc": timestamp.astimezone(timezone.utc).isoformat(),
                        "resource_id": definition[3],
                        "metric": definition[1],
                        "statistic": definition[4],
                        "value": value,
                        "unit": definition[5],
                    })
            next_token = response.get("NextToken")
            if not next_token:
                break
    return sorted(
        rows,
        key=lambda row: (
            row["timestamp_utc"], row["resource_id"],
            row["metric"], row["statistic"],
        ),
    )


def write_csv(path: Path, rows: list[dict]) -> None:
    """Write metric rows without replacing an existing file."""
    with path.open("x", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


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
        results = {
            name: fetch_metrics(client, definitions, args.start, args.end)
            for name, definitions in files.items()
        }
    except (BotoCoreError, ClientError) as error:
        raise SystemExit(f"CloudWatch request failed: {error}") from error
    except RuntimeError as error:
        raise SystemExit(str(error)) from error

    try:
        args.output.mkdir(parents=True, exist_ok=True)
        for name, rows in results.items():
            write_csv(args.output / name, rows)
    except FileExistsError as error:
        raise SystemExit(f"output file already exists: {error.filename}") from error
    except OSError as error:
        raise SystemExit(f"could not write CSV files: {error}") from error
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
