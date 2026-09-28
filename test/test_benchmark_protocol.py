import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test import benchmark_cpu, compare_benchmark, compare_golden, run_cpu_matrix
from test.benchmark_protocol import read_json, write_json


def benchmark_payload(cpu_percent=100.0, control_cadence_hz=30.0, frame_age_p95=10.0, queue_depth_max=1.0):
    return {
        "schema_version": 1,
        "artifact_type": "cpu-benchmark",
        "metrics": {
            "cpu_percent": cpu_percent,
            "inference_fps": 30.0,
            "frame_age_ms": {"avg": frame_age_p95, "p50": frame_age_p95, "p95": frame_age_p95, "max": frame_age_p95},
            "preprocess_ms": {"avg": 1.0, "p50": 1.0, "p95": 1.0, "max": 1.0},
            "postprocess_ms": {"avg": 1.0, "p50": 1.0, "p95": 1.0, "max": 1.0},
            "control_cadence_hz": control_cadence_hz,
            "ui_emit_cadence_hz": 0.0,
            "queue_depth": {"avg": queue_depth_max, "p95": queue_depth_max, "max": queue_depth_max},
            "timer_stat_overhead_ms": {"avg": 0.1, "p50": 0.1, "p95": 0.1, "max": 0.1},
        },
    }


class BenchmarkProtocolTest(unittest.TestCase):
    def test_missing_required_metric_fails_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            write_json(path, {"metrics": {"cpu_percent": 1.0}})

            code = compare_benchmark.main(["--baseline", str(path), "--validate-only"])

            self.assertEqual(code, 1)

    def test_identical_benchmark_artifact_passes_comparator(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.npz"
            benchmark = Path(tmp) / "benchmark.json"
            self.assertEqual(
                benchmark_cpu.main(
                    ["--cfg", "config/config.yaml", "--duration", "1", "--mode", "no-gui", "--capture-source", "--output", str(source)]
                ),
                0,
            )
            self.assertEqual(
                benchmark_cpu.main(
                    ["--cfg", "config/config.yaml", "--duration", "1", "--mode", "no-gui", "--source", str(source), "--output", str(benchmark)]
                ),
                0,
            )

            payload = read_json(benchmark)
            self.assertIn("metrics", payload)
            self.assertEqual(
                compare_benchmark.main(
                    [
                        "--baseline",
                        str(benchmark),
                        "--candidate",
                        str(benchmark),
                        "--assert-cpu-drop",
                        "0",
                        "--assert-control-regression",
                        "0",
                        "--assert-frame-age-regression",
                        "0",
                        "--assert-queue-depth",
                        "1",
                    ]
                ),
                0,
            )

    def test_identical_golden_artifact_passes_comparator(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.npz"
            golden = Path(tmp) / "golden.json"
            benchmark_cpu.main(["--cfg", "config/config.yaml", "--duration", "1", "--mode", "no-gui", "--capture-source", "--output", str(source)])
            benchmark_cpu.main(
                [
                    "--cfg",
                    "config/config.yaml",
                    "--duration",
                    "1",
                    "--mode",
                    "no-gui",
                    "--source",
                    str(source),
                    "--capture-golden",
                    "--output",
                    str(golden),
                ]
            )

            self.assertEqual(
                compare_golden.main(["--baseline", str(golden), "--candidate", str(golden), "--tolerance", "0"]),
                0,
            )

    def test_gui_benchmark_reports_ui_preview_throttle_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.npz"
            benchmark = Path(tmp) / "benchmark.json"
            benchmark_cpu.main(
                ["--cfg", "config/config.yaml", "--duration", "1", "--mode", "no-gui", "--capture-source", "--output", str(source)]
            )
            benchmark_cpu.main(
                ["--cfg", "config/config.yaml", "--duration", "1", "--mode", "gui", "--source", str(source), "--output", str(benchmark)]
            )

            payload = read_json(benchmark)

            self.assertIn("ui_preview_target_fps", payload["scheduler"])
            self.assertEqual(payload["scheduler"]["ui_preview_target_fps"], 20.0)
            self.assertEqual(payload["scheduler"]["ui_preview_policy"], "latest-only-throttle")
            self.assertLessEqual(payload["metrics"]["ui_emit_cadence_hz"], 20.0)

    def test_no_gui_benchmark_reports_ui_preview_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.npz"
            benchmark = Path(tmp) / "benchmark.json"
            benchmark_cpu.main(
                ["--cfg", "config/config.yaml", "--duration", "1", "--mode", "no-gui", "--capture-source", "--output", str(source)]
            )
            benchmark_cpu.main(
                ["--cfg", "config/config.yaml", "--duration", "1", "--mode", "no-gui", "--source", str(source), "--output", str(benchmark)]
            )

            payload = read_json(benchmark)

            self.assertIn("ui_preview_enabled", payload["scheduler"])
            self.assertFalse(payload["scheduler"]["ui_preview_enabled"])
            self.assertEqual(payload["metrics"]["ui_emit_cadence_hz"], 0.0)

    def test_cpu_matrix_report_records_passing_gate_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "matrix.json"
            baseline_paths = {}
            for scenario in ("baseline", "gui", "stress", "capture_failure"):
                path = Path(tmp) / f"{scenario}.json"
                write_json(path, benchmark_payload())
                baseline_paths[scenario] = path

            with patch(
                "test.run_cpu_matrix.run_synthetic_benchmark",
                return_value=benchmark_payload(cpu_percent=65.0, control_cadence_hz=30.0, frame_age_p95=11.0, queue_depth_max=1.0),
            ):
                code = run_cpu_matrix.main(
                    [
                        "--cfg",
                        "config/config.yaml",
                        "--source",
                        "source.npz",
                        "--baseline",
                        str(baseline_paths["baseline"]),
                        "--gui-baseline",
                        str(baseline_paths["gui"]),
                        "--stress-baseline",
                        str(baseline_paths["stress"]),
                        "--capture-failure-baseline",
                        str(baseline_paths["capture_failure"]),
                        "--output",
                        str(output),
                    ]
                )

            report = read_json(output)
            self.assertEqual(code, 0)
            self.assertTrue(report["passed"])
            self.assertEqual(report["failures"], [])
            for scenario in ("no_gui", "gui", "capture_overrun", "capture_failure"):
                result = report["gate_results"][scenario]
                self.assertTrue(result["passed"])
                self.assertEqual(result["failures"], [])
                self.assertEqual(result["cpu_drop_percent"], 35.0)
                self.assertEqual(result["control_cadence_regression_percent"], 0.0)
                self.assertEqual(result["p95_frame_age_regression_percent"], 10.0)
                self.assertEqual(result["queue_depth_max"], 1.0)

    def test_cpu_matrix_exits_nonzero_and_records_failed_gates(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "matrix.json"
            baseline_paths = {}
            for scenario in ("baseline", "gui", "stress", "capture_failure"):
                path = Path(tmp) / f"{scenario}.json"
                write_json(path, benchmark_payload())
                baseline_paths[scenario] = path

            with patch(
                "test.run_cpu_matrix.run_synthetic_benchmark",
                return_value=benchmark_payload(cpu_percent=80.0, control_cadence_hz=25.0, frame_age_p95=12.0, queue_depth_max=2.0),
            ):
                code = run_cpu_matrix.main(
                    [
                        "--cfg",
                        "config/config.yaml",
                        "--source",
                        "source.npz",
                        "--baseline",
                        str(baseline_paths["baseline"]),
                        "--gui-baseline",
                        str(baseline_paths["gui"]),
                        "--stress-baseline",
                        str(baseline_paths["stress"]),
                        "--capture-failure-baseline",
                        str(baseline_paths["capture_failure"]),
                        "--output",
                        str(output),
                    ]
                )

            report = read_json(output)
            self.assertEqual(code, 1)
            self.assertFalse(report["passed"])
            self.assertGreater(len(report["failures"]), 0)
            result = report["gate_results"]["no_gui"]
            self.assertFalse(result["passed"])
            self.assertIn("CPU drop 20.000% is below required 30.000%", result["failures"])
            self.assertIn("control cadence regression 16.667% exceeds 10.000%", result["failures"])
            self.assertIn("queue depth 2.000 exceeds 1.000", result["failures"])


if __name__ == "__main__":
    unittest.main()
