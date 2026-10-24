"""Offline tests for CloudWatch CSV evidence."""

import csv
import importlib.util
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PATH = Path(__file__).resolve().parents[1] / "load-tests" / "cloudwatch.py"
spec = importlib.util.spec_from_file_location("cloudwatch_exporter", PATH)
cloudwatch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cloudwatch)
START = datetime.fromisoformat("2026-10-24T14:59:28.276404+00:00")
END = datetime.fromisoformat("2026-10-24T14:59:58.411059+00:00")
STAMP = datetime(2026, 10, 24, 14, 59, tzinfo=timezone.utc)


class Client:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    def get_metric_data(self, **kwargs):
        self.requests.append(kwargs)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def response(request, values=None, status="Complete", token=None):
    values = values or {}
    return {
        "MetricDataResults": [
            {"Id": query["Id"], "StatusCode": status,
             "Timestamps": [STAMP] if index in values else [],
             "Values": [values[index]] if index in values else []}
            for index, query in enumerate(request["MetricDataQueries"])
        ],
        **({"NextToken": token} if token else {}),
    }


class CloudWatchTests(unittest.TestCase):
    def test_waiting_for_alb_does_not_refetch_ec2_or_rds(self):
        start = datetime.fromisoformat("2026-10-24T15:13:44+00:00")
        end = datetime.fromisoformat("2026-10-24T15:14:14+00:00")
        first = datetime.fromisoformat("2026-10-24T15:13:00+00:00")
        second = datetime.fromisoformat("2026-10-24T15:14:00+00:00")
        files = cloudwatch.requested_metrics(SimpleNamespace(
            instances=["i-product"], alb="app/product-alb/xyz", rds="product-db"))

        class DelayedClient:
            def __init__(self):
                self.namespaces = []
                self.alb_calls = 0

            def get_metric_data(self, **request):
                namespace = request["MetricDataQueries"][0]["MetricStat"]["Metric"]["Namespace"]
                self.namespaces.append(namespace)
                if namespace == "AWS/ApplicationELB":
                    self.alb_calls += 1
                stamps = [first, second] if self.alb_calls == 2 else [first]
                return {"MetricDataResults": [
                    {"Id": query["Id"], "StatusCode": "Complete",
                     "Timestamps": stamps if namespace == "AWS/ApplicationELB" and index == 2 else [first],
                     "Values": [1] * len(stamps) if namespace == "AWS/ApplicationELB" and index == 2 else [1]}
                    for index, query in enumerate(request["MetricDataQueries"])
                ]}

        client = DelayedClient()
        with tempfile.TemporaryDirectory() as temporary, patch.object(cloudwatch.time, "sleep"):
            cloudwatch.export(client, files, start, end, Path(temporary))
        self.assertEqual(client.namespaces, [
            "AWS/EC2", "AWS/ApplicationELB", "AWS/RDS", "AWS/ApplicationELB",
        ])

    def test_cross_minute_waits_for_second_request_count_and_writes_once(self):
        start = datetime.fromisoformat("2026-10-24T15:13:44.850369+00:00")
        end = datetime.fromisoformat("2026-10-24T15:14:14.993027+00:00")
        first = datetime.fromisoformat("2026-10-24T15:13:00+00:00")
        second = datetime.fromisoformat("2026-10-24T15:14:00+00:00")
        files = cloudwatch.requested_metrics(SimpleNamespace(
            instances=None, alb="app/product-alb/xyz", rds=None))

        class DelayedClient:
            def __init__(self):
                self.calls = 0
                self.requests = []

            def get_metric_data(self, **request):
                self.calls += 1
                self.requests.append(request)
                points = [(first, 15)] if self.calls == 1 else [(first, 15), (second, 16)]
                return {"MetricDataResults": [
                    {"Id": query["Id"], "StatusCode": "Complete",
                     "Timestamps": [stamp for stamp, _ in points] if index == 2 else [],
                     "Values": [value for _, value in points] if index == 2 else []}
                    for index, query in enumerate(request["MetricDataQueries"])
                ]}

        client = DelayedClient()
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            cloudwatch.time, "sleep", return_value=None
        ) as sleep:
            cloudwatch.export(client, files, start, end, Path(temporary))
            with (Path(temporary) / "alb_metrics.csv").open(newline="") as source:
                rows = list(csv.DictReader(source))
        self.assertEqual(client.calls, 2)
        self.assertEqual(client.requests[0]["StartTime"], first)
        self.assertEqual(client.requests[0]["EndTime"],
                         datetime.fromisoformat("2026-10-24T15:15:00+00:00"))
        self.assertEqual([(row["timestamp_utc"], row["value"]) for row in rows
                          if row["metric"] == "RequestCount"],
                         [(first.isoformat(), "15"), (second.isoformat(), "16")])
        sleep.assert_called_once()

    def test_timeout_preserves_first_period_and_fails(self):
        start = datetime.fromisoformat("2026-10-24T15:13:44+00:00")
        end = datetime.fromisoformat("2026-10-24T15:14:14+00:00")
        files = cloudwatch.requested_metrics(SimpleNamespace(
            instances=None, alb="app/product-alb/xyz", rds=None))
        first = datetime.fromisoformat("2026-10-24T15:13:00+00:00")
        client = Client([{
            "MetricDataResults": [
                {"Id": f"m{i}", "StatusCode": "Complete",
                 "Timestamps": [first] if i == 2 else [],
                 "Values": [15] if i == 2 else []}
                for i in range(4)
            ]
        }])
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            cloudwatch.time, "monotonic", side_effect=[0, 300]
        ):
            with self.assertRaisesRegex(RuntimeError, "15:14"):
                cloudwatch.export(client, files, start, end, Path(temporary))
            with (Path(temporary) / "alb_metrics.csv").open(newline="") as source:
                rows = list(csv.DictReader(source))
        self.assertEqual([(row["metric"], row["value"]) for row in rows
                          if row["metric"] == "RequestCount"], [("RequestCount", "15")])

    def test_confirmed_request_count_is_exported_from_partial_minute(self):
        start = datetime.fromisoformat("2026-10-24T15:07:03+00:00")
        end = datetime.fromisoformat("2026-10-24T15:07:33+00:00")
        stamp = datetime.fromisoformat("2026-10-24T15:07:00+00:00")
        files = cloudwatch.requested_metrics(SimpleNamespace(
            instances=None, alb="app/product-alb/xyz", rds=None))

        class WindowClient:
            def __init__(self):
                self.request = None

            def get_metric_data(self, **request):
                self.request = request
                included = request["StartTime"] <= stamp < request["EndTime"]
                return {"MetricDataResults": [
                    {"Id": query["Id"], "StatusCode": "Complete",
                     "Timestamps": [stamp] if included and index == 2 else [],
                     "Values": [31] if included and index == 2 else []}
                    for index, query in enumerate(request["MetricDataQueries"])
                ]}

        client = WindowClient()
        with tempfile.TemporaryDirectory() as temporary:
            cloudwatch.export(client, files, start, end, Path(temporary))
            with (Path(temporary) / "alb_metrics.csv").open(newline="") as source:
                rows = list(csv.DictReader(source))
        self.assertEqual(client.request["StartTime"], stamp)
        self.assertEqual(client.request["EndTime"],
                         datetime.fromisoformat("2026-10-24T15:08:00+00:00"))
        self.assertTrue(any(row["timestamp_utc"] == stamp.isoformat()
                            and row["metric"] == "RequestCount" and row["value"] == "31"
                            for row in rows))
        self.assertFalse(any(row["metric"] == "Target5XXErrorRate" for row in rows))

    def test_end_on_minute_boundary_includes_that_minute(self):
        start = datetime.fromisoformat("2026-10-24T15:07:03+00:00")
        end = datetime.fromisoformat("2026-10-24T15:08:00+00:00")
        metric = cloudwatch.requested_metrics(SimpleNamespace(
            instances=["i-product"], alb=None, rds=None))["ec2_cpu.csv"]
        client = Client([response({"MetricDataQueries": [{"Id": "m0"}]}, {0: 12})])
        cloudwatch.fetch_metrics(client, metric, start, end)
        self.assertEqual(client.requests[0]["StartTime"],
                         datetime.fromisoformat("2026-10-24T15:07:00+00:00"))
        self.assertEqual(client.requests[0]["EndTime"],
                         datetime.fromisoformat("2026-10-24T15:09:00+00:00"))

    def test_window_includes_complete_minute_buckets(self):
        client = Client([])
        client.responses = iter([response({"MetricDataQueries": [{"Id": "m0"}]}, {0: 12})])
        metric = cloudwatch.requested_metrics(SimpleNamespace(
            instances=["i-product"], alb=None, rds=None))["ec2_cpu.csv"]
        cloudwatch.fetch_metrics(client, metric, START, END)
        self.assertEqual(client.requests[0]["StartTime"], STAMP)
        self.assertEqual(client.requests[0]["EndTime"],
                         datetime(2026, 10, 24, 15, 0, tzinfo=timezone.utc))

    def test_empty_and_partial_results_fail(self):
        metric = cloudwatch.requested_metrics(SimpleNamespace(
            instances=["i-product"], alb=None, rds=None))["ec2_cpu.csv"]
        for result in (response({"MetricDataQueries": [{"Id": "m0"}]}, {0: 12}, "PartialData"),):
            with self.subTest(result=result), self.assertRaises(RuntimeError):
                cloudwatch.fetch_metrics(Client([result]), metric, START, END)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            with patch.object(cloudwatch.time, "monotonic", side_effect=[0, 300]):
                with self.assertRaises(RuntimeError):
                    cloudwatch.export(Client([response({"MetricDataQueries": [{"Id": "m0"}]})]),
                                      {"ec2_cpu.csv": metric}, START, END, path)
            self.assertEqual((path / "ec2_cpu.csv").read_text().count("\n"), 1)

    def test_valid_export_writes_populated_csvs_and_dimensions(self):
        files = cloudwatch.requested_metrics(SimpleNamespace(
            instances=["i-product"], alb="app/product-alb/xyz", rds="product-db"))
        client = Client([])
        client.responses = iter([
            response({"MetricDataQueries": [{"Id": "m0"}]}, {0: 12}),
            response({"MetricDataQueries": [{"Id": f"m{i}"} for i in range(4)]}, {0: .1, 1: .2, 2: 31}),
            response({"MetricDataQueries": [{"Id": f"m{i}"} for i in range(2)]}, {0: 15, 1: 3}),
        ])
        with tempfile.TemporaryDirectory() as temporary:
            results = cloudwatch.export(client, files, START, END, Path(temporary))
            self.assertEqual(set(results), set(files))
            for name in files:
                with (Path(temporary) / name).open(newline="") as source:
                    rows = list(csv.DictReader(source))
                self.assertTrue(rows, name)
                self.assertEqual(rows[0]["timestamp_utc"], STAMP.isoformat())
            with (Path(temporary) / "alb_metrics.csv").open(newline="") as source:
                self.assertTrue(any(row["metric"] == "RequestCount" and row["value"] == "31"
                                    for row in csv.DictReader(source)))
        self.assertEqual([request["MetricDataQueries"][0]["MetricStat"]["Metric"]["Dimensions"][0]
                          for request in client.requests], [
            {"Name": "InstanceId", "Value": "i-product"},
            {"Name": "LoadBalancer", "Value": "app/product-alb/xyz"},
            {"Name": "DBInstanceIdentifier", "Value": "product-db"},
        ])

    def test_pagination_and_missing_result_are_checked(self):
        metric = cloudwatch.requested_metrics(SimpleNamespace(
            instances=["i-product"], alb=None, rds=None))["ec2_cpu.csv"]
        first = response({"MetricDataQueries": [{"Id": "m0"}]}, {0: 12}, token="more")
        second = response({"MetricDataQueries": [{"Id": "m0"}]}, {0: 13})
        client = Client([first, second])
        self.assertEqual(len(cloudwatch.fetch_metrics(client, metric, START, END)), 2)
        self.assertEqual(client.requests[1]["NextToken"], "more")
        with self.assertRaises(RuntimeError):
            cloudwatch.fetch_metrics(Client([{"MetricDataResults": []}]), metric, START, END)
        first["MetricDataResults"][0]["StatusCode"] = "PartialData"
        self.assertEqual(len(cloudwatch.fetch_metrics(Client([first, second]), metric, START, END)), 2)

    def test_api_error_propagates(self):
        metric = cloudwatch.requested_metrics(SimpleNamespace(
            instances=["i-product"], alb=None, rds=None))["ec2_cpu.csv"]
        with self.assertRaisesRegex(RuntimeError, "API failed"):
            cloudwatch.fetch_metrics(Client([RuntimeError("API failed")]), metric, START, END)

    def test_later_api_failure_preserves_earlier_csv(self):
        files = cloudwatch.requested_metrics(SimpleNamespace(
            instances=["i-product"], alb="app/product-alb/xyz", rds=None))
        client = Client([
            response({"MetricDataQueries": [{"Id": "m0"}]}, {0: 12}),
            RuntimeError("API failed"),
        ])
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(RuntimeError, "API failed"):
                cloudwatch.export(client, files, START, END, Path(temporary))
            with (Path(temporary) / "ec2_cpu.csv").open(newline="") as source:
                self.assertEqual(len(list(csv.DictReader(source))), 1)


if __name__ == "__main__":
    unittest.main()
