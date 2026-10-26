"""Read-only AWS event snapshots taken while a student-run k6 trial is active."""

import json
import threading
from datetime import datetime, timezone
from pathlib import Path


def snapshot(asg, elbv2, cloudwatch, asg_name: str, target_group_arn: str) -> dict:
    """Preserve native AWS responses and discover members without fixed IDs."""
    groups = asg.describe_auto_scaling_groups(AutoScalingGroupNames=[asg_name])
    if len(groups.get("AutoScalingGroups", [])) != 1:
        raise ValueError(f"Auto Scaling Group {asg_name!r} was not found")
    policies = asg.describe_policies(AutoScalingGroupName=asg_name)
    names = sorted({alarm["AlarmName"] for policy in policies.get("ScalingPolicies", [])
                    for alarm in policy.get("Alarms", [])})
    return {
        "asg": groups,
        "activities": asg.describe_scaling_activities(
            AutoScalingGroupName=asg_name, MaxRecords=100),
        "targets": elbv2.describe_target_health(TargetGroupArn=target_group_arn),
        "policies": policies,
        "alarms": cloudwatch.describe_alarms(AlarmNames=names) if names else None,
    }


def instance_ids(record: dict) -> set[str]:
    """Collect Product IDs seen in either membership or target health."""
    groups = record["data"]["asg"]["AutoScalingGroups"]
    members = {item["InstanceId"] for group in groups for item in group["Instances"]}
    targets = {item["Target"]["Id"] for item in
               record["data"]["targets"].get("TargetHealthDescriptions", [])}
    return members | targets


class Observer:
    """Write append-only JSONL observations until the workload ends."""

    def __init__(self, session, asg_name: str, target_group_arn: str,
                 output: Path, interval: int = 15):
        from botocore.config import Config

        config = Config(connect_timeout=5, read_timeout=10,
                        retries={"max_attempts": 2, "mode": "standard"})
        self.asg = session.client("autoscaling", config=config)
        self.elbv2 = session.client("elbv2", config=config)
        self.cloudwatch = session.client("cloudwatch", config=config)
        self.asg_name = asg_name
        self.target_group_arn = target_group_arn
        self.output = output
        self.interval = interval
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.seen_ids: set[str] = set()
        self.samples = 0
        self.errors = 0

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> bool:
        self.stop_event.set()
        self.thread.join(timeout=90)
        return not self.thread.is_alive()

    def _run(self) -> None:
        with self.output.open("x", encoding="utf-8") as stream:
            while True:
                record = {"observed_utc": datetime.now(timezone.utc).isoformat()}
                try:
                    record["data"] = snapshot(self.asg, self.elbv2, self.cloudwatch,
                                              self.asg_name, self.target_group_arn)
                    self.seen_ids.update(instance_ids(record))
                    self.samples += 1
                    groups = record["data"]["asg"]["AutoScalingGroups"]
                    healthy = sum(item["TargetHealth"]["State"] == "healthy" for item in
                                  record["data"]["targets"].get("TargetHealthDescriptions", []))
                    print(f"AWS observation {self.samples}: desired={groups[0]['DesiredCapacity']} "
                          f"members={len(groups[0]['Instances'])} healthy={healthy}", flush=True)
                except Exception as error:
                    self.errors += 1
                    record["error"] = f"{type(error).__name__}: {error}"
                    print(f"AWS observation failed: {type(error).__name__}", flush=True)
                stream.write(json.dumps(record, default=str) + "\n")
                stream.flush()
                if self.stop_event.wait(self.interval):
                    break
