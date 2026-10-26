"""Offline checks for scaled, elasticity and failure runner behaviour."""

import importlib.util
import io
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from contextlib import redirect_stdout
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("experiment_runner", ROOT / "load-tests/run.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
from observe import instance_ids, snapshot


OUTPUTS = {
    "alb_url": "http://local-alb.example",
    "product_asg_name": "product-asg",
    "target_group_arn": "arn:aws:elasticloadbalancing:eu-west-1:123:targetgroup/products/abc",
    "rds_identifier": "product-db",
    "experiment_profile": "baseline",
}


def aws_mocks(experiment, states=None):
    count = runner.EXPERIMENTS[experiment]["members"]
    ids = [f"i-{index}" for index in range(count)]
    asg = MagicMock()
    asg.describe_auto_scaling_groups.return_value = {"AutoScalingGroups": [{
        "AutoScalingGroupName": "product-asg", "DesiredCapacity": count,
        "Instances": [{"InstanceId": item, "LifecycleState": "InService"} for item in ids],
    }]}
    elbv2 = MagicMock()
    elbv2.describe_target_groups.return_value = {"TargetGroups": [{"LoadBalancerArns": [
        "arn:aws:elasticloadbalancing:eu-west-1:123:loadbalancer/app/product-alb/xyz"]}]}
    elbv2.describe_target_health.return_value = {"TargetHealthDescriptions": [
        {"Target": {"Id": item}, "TargetHealth": {"State": state}}
        for item, state in zip(ids, states or ["healthy"] * count)]}
    session = MagicMock()
    session.client.side_effect = {"autoscaling": asg, "elbv2": elbv2}.__getitem__
    return session, asg, elbv2, ids


class ExperimentTests(unittest.TestCase):
    def test_scaled_and_failure_require_two_healthy_members(self):
        for experiment in ("scaled", "failure"):
            with self.subTest(experiment=experiment):
                session, _, elbv2, ids = aws_mocks(experiment)
                with patch.dict(sys.modules, {"boto3": SimpleNamespace(Session=MagicMock(
                        return_value=session))}):
                    result = runner.discover_resources(
                        {**OUTPUTS, "experiment_profile": experiment}, experiment)
                self.assertEqual(result["product_instance_ids"], ids)
                elbv2.describe_target_health.assert_called_once()

                session, _, _, _ = aws_mocks(experiment, ["healthy", "unhealthy"])
                with patch.dict(sys.modules, {"boto3": SimpleNamespace(Session=MagicMock(
                        return_value=session))}):
                    with self.assertRaisesRegex(ValueError, "healthy"):
                        runner.discover_resources(
                            {**OUTPUTS, "experiment_profile": experiment}, experiment)

    def test_elasticity_requires_one_healthy_member(self):
        session, _, _, _ = aws_mocks("elasticity")
        with patch.dict(sys.modules, {"boto3": SimpleNamespace(Session=MagicMock(
                return_value=session))}):
            result = runner.discover_resources(
                {**OUTPUTS, "experiment_profile": "elasticity"}, "elasticity")
        self.assertEqual(result["product_instance_ids"], ["i-0"])

    def test_unsupported_profile_rejected_before_aws_or_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            outputs = Path(temporary) / "outputs.json"
            values = {**OUTPUTS, "experiment_profile": "other"}
            outputs.write_text(json.dumps({key: {"value": value} for key, value in values.items()}))
            with (patch.object(runner, "discover_resources") as discover,
                  patch.object(sys, "argv", ["run.py", "--outputs", str(outputs)]),
                  patch.object(runner, "ROOT", Path(temporary))):
                with self.assertRaises(SystemExit) as result:
                    runner.main()
            self.assertEqual(result.exception.code, 1)
            discover.assert_not_called()
            self.assertFalse((Path(temporary) / "evidence").exists())

    def test_each_profile_is_selected_from_outputs_before_aws(self):
        for profile in runner.EXPERIMENTS:
            with self.subTest(profile=profile), tempfile.TemporaryDirectory() as temporary:
                outputs = Path(temporary) / "outputs.json"
                values = {**OUTPUTS, "experiment_profile": profile}
                outputs.write_text(json.dumps({key: {"value": value}
                                               for key, value in values.items()}))
                ramp = (["--low-rate", "1", "--pre-duration", "1m",
                         "--rise-duration", "1m", "--fall-duration", "1m",
                         "--post-duration", "1m"] if profile == "elasticity" else [])
                with (patch.object(runner, "discover_resources",
                                   side_effect=ValueError("offline stop")) as discover,
                      patch.object(sys, "argv", ["run.py", "--outputs", str(outputs), *ramp]),
                      patch.object(runner, "ROOT", Path(temporary))):
                    with self.assertRaises(SystemExit) as result:
                        runner.main()
                self.assertEqual(result.exception.code, 1)
                self.assertEqual(discover.call_args.args, (values, profile))
                self.assertFalse((Path(temporary) / "evidence").exists())

    def test_ramp_command_and_metadata_keep_baseline_fields(self):
        resources = {**OUTPUTS, "region": "eu-west-1", "alb_dimension": "app/alb/xyz",
                     "product_instance_id": "i-0", "product_instance_ids": ["i-0"],
                     "experiment_profile": "elasticity"}
        ramp = {"low_rate_per_second": 10, "pre_duration": "2m", "rise_duration": "1m",
                "fall_duration": "1m", "post_duration": "5m"}
        with tempfile.TemporaryDirectory() as temporary, patch.object(runner, "ROOT", Path(temporary)):
            directory, metadata = runner.setup_experiment(Path("outputs.json"), resources,
                650, "15m", 100, "elasticity", ramp)
            self.assertTrue(directory.name.startswith("elasticity-"))
            self.assertEqual(metadata["provisioned_profile"], "elasticity")
            with patch.object(runner.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as run:
                with patch.object(runner, "valid_k6_evidence", return_value=True):
                    self.assertTrue(runner.run_k6(directory, resources, metadata))
            command = run.call_args.args[0]
            self.assertEqual(command[-1], str(runner.RAMP_WORKLOAD))
            self.assertIn("HIGH_RATE=650", command)
            self.assertIn("LOW_RATE=10", command)
            self.assertIn("POST_DURATION=5m", command)
            self.assertEqual(json.loads((directory / "run.json").read_text())["workload"]["ramp"], ramp)

    def test_observer_snapshot_discovers_replacement_and_preserves_errors(self):
        asg = MagicMock()
        asg.describe_auto_scaling_groups.return_value = {"AutoScalingGroups": [{
            "DesiredCapacity": 2, "Instances": [{"InstanceId": "i-survivor"},
                                                {"InstanceId": "i-new"}]}]}
        asg.describe_scaling_activities.return_value = {"Activities": [{"ActivityId": "a-1"}]}
        asg.describe_policies.return_value = {"ScalingPolicies": []}
        elbv2 = MagicMock()
        elbv2.describe_target_health.return_value = {"TargetHealthDescriptions": [
            {"Target": {"Id": "i-old"}, "TargetHealth": {"State": "draining"}},
            {"Target": {"Id": "i-new"}, "TargetHealth": {"State": "healthy"}}]}
        data = snapshot(asg, elbv2, MagicMock(), "product-asg", OUTPUTS["target_group_arn"])
        self.assertEqual(instance_ids({"data": data}), {"i-survivor", "i-new", "i-old"})
        with tempfile.TemporaryDirectory() as temporary:
            observer = runner.Observer.__new__(runner.Observer)
            observer.asg, observer.elbv2, observer.cloudwatch = asg, elbv2, MagicMock()
            observer.asg_name, observer.target_group_arn = "product-asg", OUTPUTS["target_group_arn"]
            observer.output = Path(temporary) / "observations.jsonl"
            observer.interval = 15
            observer.stop_event = threading.Event()
            observer.seen_ids, observer.samples, observer.errors = set(), 0, 0
            with patch.object(observer.stop_event, "wait", return_value=True):
                observer._run()
            saved = json.loads(observer.output.read_text().splitlines()[0])
            self.assertIn("observed_utc", saved)
            self.assertEqual(observer.seen_ids, {"i-survivor", "i-new", "i-old"})
            self.assertEqual(observer.samples, 1)

    def test_failure_threshold_exit_still_reconciles_and_exports_new_member(self):
        resources = {**OUTPUTS, "region": "eu-west-1", "alb_dimension": "app/alb/xyz",
                     "product_instance_id": "i-old", "product_instance_ids": ["i-old", "i-survivor"],
                     "experiment_profile": "failure"}
        with tempfile.TemporaryDirectory() as temporary, patch.object(runner, "ROOT", Path(temporary)):
            outputs = Path(temporary) / "outputs.json"
            outputs.write_text(json.dumps({key: {"value": value} for key, value in
                                           {**OUTPUTS, "experiment_profile": "failure"}.items()}))
            observer = MagicMock()
            observer.stop.return_value = True
            observer.samples, observer.errors, observer.seen_ids = 2, 0, {"i-new"}

            def failed_k6(directory, found, metadata):
                metadata["k6_exit_code"] = 99
                metadata["test_start_utc"] = "2026-10-26T10:00:00+00:00"
                metadata["test_end_utc"] = "2026-10-26T10:01:00+00:00"
                metadata["status"] = "failed"
                runner.save_metadata(directory, metadata)
                return False

            with (patch.object(runner, "discover_resources", return_value=resources),
                  patch.object(runner, "Observer", return_value=observer),
                  patch.object(runner, "run_k6", side_effect=failed_k6),
                  patch.object(runner, "collect_cloudwatch", return_value=True) as collect,
                  patch.object(runner, "reconcile_requests") as reconcile,
                  patch.dict(sys.modules, {"boto3": SimpleNamespace(Session=MagicMock())}),
                  patch.object(sys, "argv", ["run.py", "--outputs", str(outputs)]),
                  redirect_stdout(io.StringIO())):
                self.assertEqual(runner.main(), 1)
            self.assertEqual(collect.call_args.args[1]["product_instance_ids"],
                             ["i-new", "i-old", "i-survivor"])
            reconcile.assert_called_once()
            folder = next((Path(temporary) / "evidence").iterdir())
            metadata = json.loads((folder / "run.json").read_text())
            self.assertEqual(metadata["observation"]["instance_ids"], ["i-new"])


if __name__ == "__main__":
    unittest.main()
