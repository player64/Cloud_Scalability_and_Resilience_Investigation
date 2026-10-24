"""Offline acceptance tests for the baseline experiment runner."""

import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


RUNNER_PATH = Path(__file__).resolve().parents[1] / "load-tests" / "run.py"
spec = importlib.util.spec_from_file_location("product_runner", RUNNER_PATH)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)

OUTPUTS = {
    "alb_url": "http://local-alb.example",
    "product_asg_name": "product-asg",
    "target_group_arn": "arn:aws:elasticloadbalancing:eu-west-1:123:targetgroup/products/abc",
    "rds_identifier": "product-db",
}
RESOURCES = {
    **OUTPUTS,
    "region": "eu-west-1",
    "product_instance_id": "i-product",
    "alb_dimension": "app/product-alb/xyz",
}


def write_outputs(path, values=OUTPUTS):
    path.write_text(json.dumps({key: {"value": value} for key, value in values.items()}))


class RunnerTests(unittest.TestCase):
    def test_load_infrastructure_outputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "outputs.json"
            write_outputs(path)
            self.assertEqual(runner.load_infrastructure_outputs(path), OUTPUTS)

            for invalid in ({**OUTPUTS, "alb_url": ""},
                            {key: value for key, value in OUTPUTS.items() if key != "target_group_arn"}):
                with self.subTest(invalid=invalid):
                    write_outputs(path, invalid)
                    with self.assertRaises(ValueError):
                        runner.load_infrastructure_outputs(path)
            path.write_text("not json")
            with self.assertRaises(json.JSONDecodeError):
                runner.load_infrastructure_outputs(path)

    def test_discover_resources(self):
        autoscaling = MagicMock()
        autoscaling.describe_auto_scaling_groups.return_value = {
            "AutoScalingGroups": [{"AutoScalingGroupName": "product-asg", "Instances": [
                {"InstanceId": "i-product", "LifecycleState": "InService"},
                {"InstanceId": "i-starting", "LifecycleState": "Pending"},
            ]}]
        }
        elbv2 = MagicMock()
        elbv2.describe_target_groups.return_value = {
            "TargetGroups": [{"LoadBalancerArns": [
                "arn:aws:elasticloadbalancing:eu-west-1:123:loadbalancer/app/product-alb/xyz"
            ]}]
        }
        session = MagicMock()
        session.client.side_effect = {"autoscaling": autoscaling, "elbv2": elbv2}.__getitem__
        boto3 = SimpleNamespace(Session=MagicMock(return_value=session))
        with patch.dict(sys.modules, {"boto3": boto3}):
            self.assertEqual(runner.discover_resources(OUTPUTS), RESOURCES)
        boto3.Session.assert_called_once_with(region_name="eu-west-1")
        autoscaling.describe_auto_scaling_groups.assert_called_once_with(
            AutoScalingGroupNames=["product-asg"]
        )
        elbv2.describe_target_groups.assert_called_once_with(
            TargetGroupArns=[OUTPUTS["target_group_arn"]]
        )

    def run_workflow(self, k6_code=0, cloudwatch_code=0):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            outputs = root / "outputs.json"
            write_outputs(outputs)
            calls = []

            def subprocess_result(command, **kwargs):
                calls.append(command)
                if command[0] == "k6":
                    Path(command[command.index("--out") + 1][4:]).write_text("partial k6 evidence\n")
                    kwargs["stdout"].write("k6 log\n")
                    return SimpleNamespace(returncode=k6_code)
                if cloudwatch_code == "error":
                    raise OSError("CloudWatch export failed")
                (Path(command[command.index("--output") + 1]) / "cloudwatch.json").write_text("{}\n")
                return SimpleNamespace(returncode=cloudwatch_code)

            before = datetime.now(timezone.utc)
            with (patch.object(runner, "ROOT", root),
                  patch.object(runner, "discover_resources", return_value=RESOURCES),
                  patch.object(runner.subprocess, "run", side_effect=subprocess_result),
                  patch.object(sys, "argv", [str(RUNNER_PATH), "baseline", "--outputs", str(outputs)])):
                # setup_experiment, run_k6 and collect_cloudwatch remain real.
                result = runner.main()
            after = datetime.now(timezone.utc)
            directories = list((root / "evidence").iterdir())
            self.assertEqual(len(directories), 1)
            evidence = directories[0]
            metadata = json.loads((evidence / "run.json").read_text())
            self.assertEqual(metadata["experiment"], "baseline")
            self.assertEqual(metadata["outputs_file"], str(outputs.resolve()))
            self.assertEqual(metadata["resources"], RESOURCES)
            self.assertEqual(metadata["workload"], {
                "script": "load-tests/product.js", "rate_per_second": runner.REQUEST_RATE,
                "duration": runner.DURATION, "preallocated_vus": runner.VUS,
            })
            self.assertTrue((evidence / "k6.csv").exists())
            self.assertEqual((evidence / "k6.txt").read_text(), "k6 log\n")
            times = [datetime.fromisoformat(metadata[key]) for key in
                     ("created_utc", "test_start_utc", "test_end_utc")]
            self.assertTrue(all(time.utcoffset().total_seconds() == 0 for time in times))
            self.assertTrue(before <= times[0] <= times[1] <= times[2] <= after)
            return result, calls, metadata, (evidence / "cloudwatch.json").exists()

    def test_successful_workflow(self):
        result, calls, metadata, cloudwatch_exists = self.run_workflow()
        self.assertEqual(result, 0)
        self.assertEqual([call[0] for call in calls], ["k6", sys.executable])
        k6 = calls[0]
        self.assertEqual(k6[-1], str(runner.WORKLOAD))
        self.assertEqual([k6[index + 1] for index, value in enumerate(k6) if value == "-e"], [
            f"ALB_URL={OUTPUTS['alb_url']}", f"RATE={runner.REQUEST_RATE}",
            f"DURATION={runner.DURATION}", f"VUS={runner.VUS}",
        ])
        cloudwatch = calls[1]
        self.assertEqual(cloudwatch[cloudwatch.index("--instances") + 1], "i-product")
        self.assertEqual(cloudwatch[cloudwatch.index("--alb") + 1], "app/product-alb/xyz")
        self.assertEqual(cloudwatch[cloudwatch.index("--rds") + 1], "product-db")
        self.assertEqual(cloudwatch[cloudwatch.index("--start") + 1], metadata["test_start_utc"])
        self.assertEqual(cloudwatch[cloudwatch.index("--end") + 1], metadata["test_end_utc"])
        self.assertTrue(cloudwatch_exists)
        self.assertEqual((metadata["status"], metadata["k6_exit_code"],
                          metadata["cloudwatch_exit_code"]), ("completed", 0, 0))

    def test_k6_failure_stops_before_cloudwatch(self):
        result, calls, metadata, cloudwatch_exists = self.run_workflow(k6_code=7)
        self.assertEqual(result, 1)
        self.assertEqual(len(calls), 1)
        self.assertEqual(metadata["status"], "failed")
        self.assertEqual(metadata["k6_exit_code"], 7)
        self.assertIsNone(metadata["cloudwatch_exit_code"])
        self.assertFalse(cloudwatch_exists)

    def test_cloudwatch_failure_preserves_partial_evidence(self):
        result, calls, metadata, cloudwatch_exists = self.run_workflow(cloudwatch_code="error")
        self.assertEqual(result, 1)
        self.assertEqual(len(calls), 2)
        self.assertEqual(metadata["status"], "failed")
        self.assertEqual(metadata["k6_exit_code"], 0)
        self.assertIsNone(metadata["cloudwatch_exit_code"])
        self.assertIn("CloudWatch export failed", metadata["error"])
        self.assertFalse(cloudwatch_exists)


if __name__ == "__main__":
    unittest.main()
