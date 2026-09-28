import tempfile
import unittest
from pathlib import Path

from test.benchmark_protocol import write_json
from test.promotion_gate import evaluate_phase2_promotion, write_phase2_promotion_gate


class Phase2PromotionGateTest(unittest.TestCase):
    def benchmark(self, cpu_percent, timer_avg=0.01, preprocess_avg=0.1, postprocess_avg=0.1):
        return {
            "metrics": {
                "cpu_percent": cpu_percent,
                "inference_fps": 30.0,
                "frame_age_ms": {"avg": 1.0, "p50": 1.0, "p95": 1.0, "max": 1.0},
                "preprocess_ms": {"avg": preprocess_avg, "p50": preprocess_avg, "p95": preprocess_avg, "max": preprocess_avg},
                "postprocess_ms": {"avg": postprocess_avg, "p50": postprocess_avg, "p95": postprocess_avg, "max": postprocess_avg},
                "control_cadence_hz": 30.0,
                "ui_emit_cadence_hz": 0.0,
                "queue_depth": {"avg": 1.0, "p95": 1.0, "max": 1.0},
                "timer_stat_overhead_ms": {"avg": timer_avg, "p50": timer_avg, "p95": timer_avg, "max": timer_avg},
            }
        }

    def test_phase2_is_unnecessary_when_phase1_reaches_cpu_reduction_target(self):
        decision = evaluate_phase2_promotion(self.benchmark(100.0), self.benchmark(70.0, preprocess_avg=2.0))

        self.assertEqual(decision["decision"], "unnecessary")
        self.assertAlmostEqual(decision["cpu_reduction_percent"], 30.0)
        self.assertIn("phase 1 reached the 30% CPU reduction target", decision["summary"])

    def test_phase2_requires_named_hotspots_when_cpu_target_is_missed(self):
        decision = evaluate_phase2_promotion(self.benchmark(100.0), self.benchmark(85.0, preprocess_avg=2.0, postprocess_avg=1.7))

        self.assertEqual(decision["decision"], "eligible")
        self.assertIn("preprocess_ms", decision["hotspots"])
        self.assertIn("postprocess_ms", decision["hotspots"])

    def test_gate_writes_human_readable_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            baseline = Path(tmp) / "baseline.json"
            candidate = Path(tmp) / "candidate.json"
            evidence = Path(tmp) / "gate.txt"
            write_json(baseline, self.benchmark(100.0))
            write_json(candidate, self.benchmark(75.0))

            decision = write_phase2_promotion_gate(baseline, candidate, evidence)

            self.assertEqual(decision["decision"], "blocked")
            text = evidence.read_text(encoding="utf-8")
            self.assertIn("Phase-2 native/C++ promotion gate", text)
            self.assertIn("CPU reduction: 25.000%", text)
            self.assertIn("Decision: blocked", text)


if __name__ == "__main__":
    unittest.main()
