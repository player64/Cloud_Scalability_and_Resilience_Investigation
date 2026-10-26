"""Local acceptance tests for the real k6 Product workload."""

import csv
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


WORKLOAD = Path(__file__).resolve().parents[1] / "load-tests" / "product.js"
RAMP_WORKLOAD = WORKLOAD.with_name("product-ramp.js")


@unittest.skipUnless(shutil.which("k6"), "k6 is not installed")
class ProductLoadTests(unittest.TestCase):
    def run_workload(self, status, ramp=False):
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append((self.command, self.path))
                body = b"[]" if status == 200 else b"failure"
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                summary_path = Path(directory) / "summary.json"
                csv_path = Path(directory) / "results.csv"
                result = subprocess.run(
                    ["k6", "run", "--quiet", "--summary-export", str(summary_path),
                      "--out", f"csv={csv_path}", str(RAMP_WORKLOAD if ramp else WORKLOAD)],
                    env={**os.environ, "ALB_URL": f"http://127.0.0.1:{server.server_port}/",
                         "RATE": "2", "DURATION": "3s", "VUS": "2",
                         "LOW_RATE": "1", "HIGH_RATE": "2", "PRE_DURATION": "1s",
                         "RISE_DURATION": "1s", "HIGH_DURATION": "1s",
                         "FALL_DURATION": "1s", "POST_DURATION": "1s"},
                    capture_output=True, text=True, timeout=20,
                )
                self.assertTrue(summary_path.exists(), result.stderr)
                self.assertTrue(csv_path.exists(), result.stderr)
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
                with csv_path.open(newline="", encoding="utf-8") as stream:
                    samples = list(csv.DictReader(stream))
                return result, requests, summary, samples
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_successful_requests_and_evidence(self):
        result, requests, summary, samples = self.run_workload(200)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(requests)
        self.assertEqual(set(requests), {("GET", "/productapi/products")})

        metrics = summary["metrics"]
        count = metrics["http_reqs"]["count"]
        self.assertEqual(count, len(requests))
        self.assertEqual(count, metrics["iterations"]["count"])
        self.assertGreaterEqual(count, 5)  # 2 arrivals/s for 3 seconds
        self.assertLessEqual(count, 7)
        self.assertEqual(metrics["checks"]["passes"], count)
        self.assertEqual(metrics["checks"]["fails"], 0)
        self.assertEqual(metrics["http_req_failed"]["value"], 0)
        self.assertGreaterEqual(metrics["http_req_duration"]["avg"], 0)
        self.assertGreaterEqual(metrics["http_req_duration"]["max"], 0)

        durations = [row for row in samples if row["metric_name"] == "http_req_duration"]
        self.assertEqual(len(durations), count)
        self.assertTrue(all(float(row["metric_value"]) >= 0 for row in durations))
        timestamps = [float(row["timestamp"]) for row in durations]
        self.assertGreater(max(timestamps) - min(timestamps), 1.5)
        self.assertLess(max(timestamps) - min(timestamps), 3.5)
        self.assertEqual(len([row for row in samples if row["metric_name"] == "http_req_failed"]), count)

    def test_non_200_fails_acceptance(self):
        result, requests, summary, samples = self.run_workload(503)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(requests)
        self.assertEqual(set(requests), {("GET", "/productapi/products")})
        count = summary["metrics"]["http_reqs"]["count"]
        self.assertEqual(summary["metrics"]["checks"]["fails"], count)
        self.assertEqual(summary["metrics"]["http_req_failed"]["value"], 1)
        self.assertEqual(len([row for row in samples if row["metric_name"] == "http_req_duration"]), count)

    def test_ramp_keeps_same_get_and_http_200_check(self):
        result, requests, summary, samples = self.run_workload(200, ramp=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(requests)
        self.assertEqual(set(requests), {("GET", "/productapi/products")})
        self.assertEqual(summary["metrics"]["checks"]["passes"], len(requests))
        self.assertEqual(summary["metrics"]["http_req_failed"]["value"], 0)
        self.assertTrue(any(row["metric_name"] == "http_req_duration" for row in samples))


if __name__ == "__main__":
    unittest.main()
