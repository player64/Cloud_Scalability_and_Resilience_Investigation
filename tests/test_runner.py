"""Offline acceptance tests for the baseline experiment runner."""

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
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
    "experiment_profile": "baseline",
    "evidence_bucket": "test-evidence-bucket",
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
                            {key: value for key, value in OUTPUTS.items() if key != "target_group_arn"},
                            {key: value for key, value in OUTPUTS.items() if key != "experiment_profile"},
                            {key: value for key, value in OUTPUTS.items() if key != "evidence_bucket"}):
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

    def run_workflow(self, k6_code=0, cloudwatch_code=0, valid_k6=True,
                     valid_cloudwatch=True, cli_args=(), expected_workload=None,
                     alb_counts=(31,), refresh_error=False, clock=None,
                     include_request_count=True, upload_error=False):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            outputs = root / "outputs.json"
            write_outputs(outputs)
            calls = []
            alb_exports = 0

            def subprocess_result(command, **kwargs):
                nonlocal alb_exports
                calls.append(command)
                if command[0] == "k6":
                    kwargs["stdout"].write("k6 log\n")
                    if k6_code == "error":
                        raise RuntimeError("k6 runner crashed")
                    Path(command[command.index("--out") + 1][4:]).write_text(
                        "metric_name,timestamp,metric_value\n"
                        + ("checks,1792853968000,1\nhttp_req_duration,1792853968000,123\n"
                           "iterations,1792853968000,1\n"
                           + ("http_reqs,1792853968000,31\n" if include_request_count else "")
                           if valid_k6 else "")
                    )
                    return SimpleNamespace(returncode=k6_code)
                if cloudwatch_code == "error":
                    raise OSError("CloudWatch export failed")
                if refresh_error and "--instances" not in command:
                    kwargs["stdout"].write("CloudWatch API diagnostic\n")
                    return SimpleNamespace(returncode=4)
                kwargs["stdout"].write("CloudWatch diagnostic\n")
                target = Path(command[command.index("--output") + 1])
                alb_only = "--instances" not in command
                count = alb_counts[min(alb_exports, len(alb_counts) - 1)]
                alb_exports += 1
                minute = datetime.fromisoformat(command[command.index("--start") + 1]).replace(
                    second=0, microsecond=0).isoformat()
                for name in ("ec2_cpu.csv", "alb_metrics.csv", "rds_metrics.csv"):
                    if alb_only and name != "alb_metrics.csv":
                        continue
                    if valid_cloudwatch == "missing" and name == "rds_metrics.csv":
                        continue
                    metric = f"RequestCount,Sum,{count},Count" if name == "alb_metrics.csv" else "CPUUtilization,Average,12,Percent"
                    resource = RESOURCES["alb_dimension"] if name == "alb_metrics.csv" else "resource"
                    (target / name).write_text(
                        "timestamp_utc,resource_id,metric,statistic,value,unit\n"
                        + (f"{minute},{resource},{metric}\n"
                           if valid_cloudwatch else "")
                    )
                return SimpleNamespace(returncode=cloudwatch_code)

            before = datetime.now(timezone.utc)
            terminal = io.StringIO()
            with (patch.object(runner, "ROOT", root),
                  patch.object(runner, "discover_resources", return_value=RESOURCES),
                  patch.object(runner, "upload_evidence",
                               side_effect=RuntimeError("S3 unavailable") if upload_error else None) as upload,
                  patch.object(runner.subprocess, "run", side_effect=subprocess_result),
                  patch.object(runner.time, "sleep", return_value=None),
                   patch.object(sys, "argv", [str(RUNNER_PATH), "--outputs", str(outputs),
                                             *cli_args]),
                  redirect_stdout(terminal)):
                # setup_experiment, run_k6 and collect_cloudwatch remain real.
                if clock is None:
                    result = runner.main()
                else:
                    with patch.object(runner.time, "monotonic", side_effect=clock):
                        result = runner.main()
            after = datetime.now(timezone.utc)
            upload.assert_called_once()
            directories = list((root / "evidence").iterdir())
            self.assertEqual(len(directories), 1)
            evidence = directories[0]
            metadata = json.loads((evidence / "run.json").read_text())
            self.last_evidence = {str(path.relative_to(evidence)): path.read_text()
                                  for path in evidence.rglob("*") if path.is_file()}
            self.assertEqual(metadata["experiment"], "baseline")
            self.assertEqual(metadata["outputs_file"], str(outputs.resolve()))
            self.assertEqual(metadata["resources"], RESOURCES)
            self.assertEqual(metadata["workload"], expected_workload or {
                "script": "load-tests/product.js", "rate_per_second": runner.REQUEST_RATE,
                "duration": runner.DURATION, "preallocated_vus": runner.VUS,
            })
            self.assertEqual((evidence / "k6.csv").exists(), k6_code != "error")
            self.assertEqual((evidence / "k6.txt").read_text(), "k6 log\n")
            self.assertEqual((evidence / "cloudwatch.txt").read_text(),
                             "" if cloudwatch_code == "error" else "CloudWatch diagnostic\n")
            times = [datetime.fromisoformat(metadata[key]) for key in
                     ("created_utc", "test_start_utc", "test_end_utc")]
            self.assertTrue(all(time.utcoffset().total_seconds() == 0 for time in times))
            self.assertTrue(before <= times[0] <= times[1] <= times[2] <= after)
            summary = terminal.getvalue()
            for value in ("Experiment: baseline", "k6: exit", "CloudWatch: exit",
                          f"Status: {metadata['status']}", f"Evidence: {evidence}"):
                self.assertIn(value, summary)
            workload = metadata["workload"]
            self.assertIn(
                f"{workload['rate_per_second']} req/s | {workload['duration']} | "
                f"{workload['preallocated_vus']} VUs", summary,
            )
            return result, calls, metadata, (evidence / "ec2_cpu.csv").exists()

    def test_upload_evidence_preserves_partial_files_and_final_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "evidence" / "baseline-run"
            (directory / "reconciliation").mkdir(parents=True)
            (directory / "k6.csv").write_text("partial csv\n")
            (directory / "reconciliation" / "cloudwatch.txt").write_text("error\n")
            metadata = {"status": "failed"}
            client = MagicMock()
            boto3 = SimpleNamespace(client=MagicMock(return_value=client))
            with patch.dict(sys.modules, {"boto3": boto3}):
                runner.upload_evidence(directory, metadata, "test-evidence-bucket", "eu-west-1")
            keys = [call.args[2] for call in client.upload_file.call_args_list]
            self.assertEqual(keys, [
                "evidence/baseline-run/k6.csv",
                "evidence/baseline-run/reconciliation/cloudwatch.txt",
                "evidence/baseline-run/run.json",
            ])
            self.assertEqual(json.loads((directory / "run.json").read_text())["evidence_upload"],
                             {"status": "completed", "error": None})

    def test_upload_failure_preserves_completed_run_and_reports_error(self):
        result, _, metadata, _ = self.run_workflow(upload_error=True)
        self.assertEqual(result, 1)
        self.assertEqual(metadata["status"], "completed")
        self.assertEqual(metadata["evidence_upload"],
                         {"status": "failed", "error": "RuntimeError: S3 unavailable"})

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
        self.assertEqual(metadata["k6_command"], k6)
        self.assertEqual(metadata["provisioned_profile"], "baseline")
        self.assertEqual(metadata["k6_environment"], {
            "ALB_URL": OUTPUTS["alb_url"], "RATE": str(runner.REQUEST_RATE),
            "DURATION": runner.DURATION, "VUS": str(runner.VUS),
        })
        self.assertEqual(metadata["reconciliation"], {
            "status": "matched", "k6_requests": 31, "alb_requests": 31,
            "difference": 0, "attempts": 1,
        })
        self.assertNotIn("reconciliation/", " ".join(self.last_evidence))

    def test_mismatch_retries_alb_only_and_preserves_both_exports(self):
        result, calls, metadata, _ = self.run_workflow(alb_counts=(29, 31))
        self.assertEqual(result, 0)
        self.assertEqual([call[0] for call in calls], ["k6", sys.executable, sys.executable])
        self.assertEqual(sum(call[0] == "k6" for call in calls), 1)
        self.assertNotIn("--instances", calls[2])
        self.assertNotIn("--rds", calls[2])
        self.assertEqual(metadata["reconciliation"], {
            "status": "matched", "k6_requests": 31, "alb_requests": 31,
            "difference": 0, "attempts": 2,
        })
        self.assertIn("RequestCount,Sum,29,Count",
                      self.last_evidence["reconciliation/alb_metrics_attempt_1.csv"])
        self.assertIn("RequestCount,Sum,31,Count", self.last_evidence["alb_metrics.csv"])
        self.assertEqual(self.last_evidence["k6.csv"].count("http_reqs"), 1)
        self.assertIn("ec2_cpu.csv", self.last_evidence)
        self.assertIn("rds_metrics.csv", self.last_evidence)

    def test_persistent_mismatch_times_out_and_preserves_latest_export(self):
        result, calls, metadata, _ = self.run_workflow(
            alb_counts=(29, 30), cli_args=("--reconcile-timeout", "2", "--reconcile-delay", "1"),
            clock=iter([0, 0, 1, 1, 2]),
        )
        self.assertEqual(result, 1)
        self.assertEqual(len(calls), 3)
        self.assertEqual(metadata["status"], "failed")
        self.assertEqual(metadata["reconciliation"], {
            "status": "timeout", "k6_requests": 31, "alb_requests": 30,
            "difference": -1, "attempts": 2,
            "reason": "ALB RequestCount did not reconcile before timeout",
        })
        self.assertIsNone(metadata["cloudwatch_error"])
        self.assertIn("RequestCount,Sum,30,Count", self.last_evidence["alb_metrics.csv"])

    def test_extra_alb_requests_fail_fast_without_blame_on_cloudwatch(self):
        result, calls, metadata, _ = self.run_workflow(alb_counts=(36,))
        self.assertEqual(result, 1)
        self.assertEqual(len(calls), 2)
        self.assertEqual(metadata["status"], "failed")
        self.assertEqual(metadata["cloudwatch_exit_code"], 0)
        self.assertIsNone(metadata["cloudwatch_error"])
        self.assertEqual(metadata["reconciliation"]["status"], "mismatch")
        self.assertEqual(metadata["reconciliation"]["difference"], 5)
        self.assertEqual(metadata["reconciliation"]["attempts"], 1)
        self.assertIn("overlapping", metadata["reconciliation"]["reason"])

    def test_refresh_failure_retains_diagnostic_and_original_export(self):
        result, calls, metadata, _ = self.run_workflow(
            alb_counts=(29,), refresh_error=True,
        )
        self.assertEqual(result, 1)
        self.assertEqual(len(calls), 3)
        self.assertEqual(metadata["reconciliation"]["status"], "unavailable")
        self.assertEqual(metadata["reconciliation"]["attempts"], 2)
        self.assertIn("ALB refresh exited with code 4", metadata["cloudwatch_error"])
        self.assertIn("CloudWatch API diagnostic",
                      self.last_evidence["reconciliation/attempt_2/cloudwatch.txt"])
        self.assertIn("RequestCount,Sum,29,Count", self.last_evidence["alb_metrics.csv"])

    def test_missing_request_counter_is_explicitly_unavailable(self):
        result, calls, metadata, _ = self.run_workflow(include_request_count=False)
        self.assertEqual(result, 1)
        self.assertEqual(len(calls), 2)
        self.assertEqual(metadata["reconciliation"]["status"], "unavailable")
        self.assertIsNone(metadata["reconciliation"]["k6_requests"])
        self.assertIn("k6.csv", self.last_evidence)
        self.assertIsNone(metadata["workload_error"])

    def test_custom_workload_matches_command_and_metadata(self):
        workload = {
            "script": "load-tests/product.js", "rate_per_second": 12,
            "duration": "5m", "preallocated_vus": 20,
        }
        result, calls, metadata, _ = self.run_workflow(
            cli_args=("--rate", "12", "--duration", "5m", "--vus", "20"),
            expected_workload=workload,
        )
        self.assertEqual(result, 0)
        self.assertEqual(metadata["workload"], workload)
        self.assertEqual(metadata["k6_command"], calls[0])
        self.assertEqual(metadata["k6_environment"], {
            "ALB_URL": OUTPUTS["alb_url"], "RATE": "12", "DURATION": "5m", "VUS": "20",
        })
        self.assertEqual([calls[0][index + 1] for index, value in enumerate(calls[0])
                          if value == "-e"], [
            f"ALB_URL={OUTPUTS['alb_url']}", "RATE=12", "DURATION=5m", "VUS=20",
        ])

    def test_invalid_workload_rejected_before_outputs_or_aws(self):
        invalid = (("--rate", "0"), ("--rate", "1.5"),
                   ("--duration", "0s"), ("--duration", "five minutes"),
                   ("--vus", "-2"), ("--vus", "1.5"))
        for arguments in invalid:
            with self.subTest(arguments=arguments), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                with (patch.object(runner, "ROOT", root),
                      patch.object(runner, "load_infrastructure_outputs") as outputs,
                      patch.object(runner, "discover_resources") as discover,
                      patch.object(runner.subprocess, "run") as process,
                       patch.object(sys, "argv", [str(RUNNER_PATH), *arguments]),
                      redirect_stderr(io.StringIO())):
                    with self.assertRaises(SystemExit) as exit_status:
                        runner.main()
                self.assertEqual(exit_status.exception.code, 2)
                outputs.assert_not_called()
                discover.assert_not_called()
                process.assert_not_called()
                self.assertFalse((root / "evidence").exists())

    def test_k6_failure_still_collects_cloudwatch(self):
        result, calls, metadata, cloudwatch_exists = self.run_workflow(
            k6_code=7, alb_counts=(29,),
        )
        self.assertEqual(result, 1)
        self.assertEqual(len(calls), 2)
        self.assertEqual(metadata["status"], "failed")
        self.assertEqual(metadata["k6_exit_code"], 7)
        self.assertEqual(metadata["cloudwatch_exit_code"], 0)
        self.assertIn("k6 exited with code 7", metadata["workload_error"])
        self.assertIsNone(metadata["cloudwatch_error"])
        self.assertEqual(metadata["reconciliation"], {
            "status": "skipped", "k6_requests": None, "alb_requests": None,
            "difference": None, "attempts": 0,
            "reason": "k6 execution was unsuccessful",
        })
        self.assertEqual(metadata["k6_command"], calls[0])
        self.assertEqual(metadata["k6_environment"], {
            "ALB_URL": OUTPUTS["alb_url"], "RATE": "1", "DURATION": "30s", "VUS": "2",
        })
        self.assertTrue(cloudwatch_exists)

    def test_cloudwatch_failure_preserves_partial_evidence(self):
        result, calls, metadata, cloudwatch_exists = self.run_workflow(cloudwatch_code="error")
        self.assertEqual(result, 1)
        self.assertEqual(len(calls), 2)
        self.assertEqual(metadata["status"], "failed")
        self.assertEqual(metadata["k6_exit_code"], 0)
        self.assertIsNone(metadata["cloudwatch_exit_code"])
        self.assertIn("CloudWatch export failed", metadata["cloudwatch_error"])
        self.assertFalse(cloudwatch_exists)

    def test_empty_cloudwatch_csv_fails_even_with_zero_exit(self):
        result, calls, metadata, exists = self.run_workflow(valid_cloudwatch=False)
        self.assertEqual(result, 1)
        self.assertTrue(exists)
        self.assertEqual(metadata["cloudwatch_exit_code"], 0)
        self.assertEqual(metadata["status"], "failed")
        self.assertIn("CloudWatch evidence missing or incomplete", metadata["cloudwatch_error"])

    def test_missing_required_cloudwatch_file_fails_even_with_zero_exit(self):
        result, _, metadata, _ = self.run_workflow(valid_cloudwatch="missing")
        self.assertEqual(result, 1)
        self.assertEqual(metadata["cloudwatch_exit_code"], 0)
        self.assertEqual(metadata["status"], "failed")
        self.assertIn("rds_metrics.csv", metadata["cloudwatch_error"])

    def test_empty_k6_csv_fails_and_preserves_file(self):
        result, calls, metadata, exists = self.run_workflow(valid_k6=False)
        self.assertEqual(result, 1)
        self.assertEqual(len(calls), 2)
        self.assertEqual(metadata["status"], "failed")
        self.assertIn("k6 CSV has no valid measurements", metadata["workload_error"])
        self.assertTrue(exists)

    def test_both_failures_are_recorded_independently(self):
        result, calls, metadata, exists = self.run_workflow(k6_code=99, cloudwatch_code=4)
        self.assertEqual(result, 1)
        self.assertEqual(len(calls), 2)
        self.assertEqual((metadata["k6_exit_code"], metadata["cloudwatch_exit_code"]), (99, 4))
        self.assertIn("k6 exited with code 99", metadata["workload_error"])
        self.assertIn("CloudWatch export exited with code 4", metadata["cloudwatch_error"])
        self.assertTrue(exists)

    def test_unexpected_k6_exception_still_collects_cloudwatch(self):
        result, calls, metadata, exists = self.run_workflow(k6_code="error")
        self.assertEqual(result, 1)
        self.assertEqual(len(calls), 2)
        self.assertIsNone(metadata["k6_exit_code"])
        self.assertEqual(metadata["cloudwatch_exit_code"], 0)
        self.assertIn("k6 runner crashed", metadata["workload_error"])
        self.assertIn("k6 CSV has no valid measurements", metadata["workload_error"])
        self.assertTrue(exists)

    def test_runner_rejects_one_alb_period_from_cross_minute_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "alb_metrics.csv"
            path.write_text(
                "timestamp_utc,resource_id,metric,statistic,value,unit\n"
                "2026-10-24T15:13:00+00:00,app/product-alb/xyz,RequestCount,Sum,15,Count\n"
            )
            start = "2026-10-24T15:13:44.850369+00:00"
            end = "2026-10-24T15:14:14.993027+00:00"
            self.assertFalse(runner.valid_alb_evidence(path, start, end))
            with path.open("a") as source:
                source.write(
                    "2026-10-24T15:14:00+00:00,app/product-alb/xyz,RequestCount,Sum,16,Count\n"
                )
            self.assertTrue(runner.valid_alb_evidence(path, start, end))

    def test_incomplete_cloudwatch_export_keeps_failed_run_evidence(self):
        result, calls, metadata, exists = self.run_workflow(cloudwatch_code=1)
        self.assertEqual(result, 1)
        self.assertEqual(len(calls), 2)
        self.assertEqual(metadata["status"], "failed")
        self.assertEqual(metadata["cloudwatch_exit_code"], 1)
        self.assertIn("CloudWatch export exited with code 1", metadata["cloudwatch_error"])
        self.assertTrue(exists)

    def test_zero_exit_with_one_period_cannot_complete_cross_minute_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            metadata = {
                "test_start_utc": "2026-10-24T15:13:44.850369+00:00",
                "test_end_utc": "2026-10-24T15:14:14.993027+00:00",
                "k6_exit_code": 0,
                "cloudwatch_exit_code": None,
                "status": "running",
            }
            for name in ("ec2_cpu.csv", "alb_metrics.csv", "rds_metrics.csv"):
                metric = "RequestCount,Sum,15,Count" if name == "alb_metrics.csv" else "CPUUtilization,Average,12,Percent"
                (directory / name).write_text(
                    "timestamp_utc,resource_id,metric,statistic,value,unit\n"
                    f"2026-10-24T15:13:00+00:00,resource,{metric}\n"
                )
            with patch.object(runner.subprocess, "run", return_value=SimpleNamespace(returncode=0)):
                self.assertFalse(runner.collect_cloudwatch(directory, RESOURCES, metadata))
            saved = json.loads((directory / "run.json").read_text())
            self.assertEqual(saved["status"], "failed")
            self.assertEqual(saved["cloudwatch_exit_code"], 0)
            self.assertEqual(saved["test_start_utc"], metadata["test_start_utc"])
            self.assertEqual(saved["test_end_utc"], metadata["test_end_utc"])
            self.assertTrue((directory / "alb_metrics.csv").exists())


if __name__ == "__main__":
    unittest.main()
