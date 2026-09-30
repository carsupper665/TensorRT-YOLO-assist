import io
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from test import benchmark_real


class FakeCam:
    def __init__(self, frame_age_s):
        self.frame_age_s = frame_age_s

    def get_latest_frame(self, with_timestamp=False):
        frame = object()
        if with_timestamp:
            return frame, time.perf_counter() - self.frame_age_s
        return frame


class FakeEngine:
    def infer(self, img):
        time.sleep(0.002)
        return img

    def forward(self, image):
        self.infer(image)
        return [], [], []


class FakeMain:
    """Mimics the parts of main.Main that LoopProbe wraps."""

    def __init__(self, cam_type="dxcam", frame_age_s=0.003):
        self.cam_type = cam_type
        self.cam = FakeCam(frame_age_s)
        self.engine = FakeEngine()
        self.run_engine = True
        self.grab_screen = self.cam.get_latest_frame

    def forward(self, tick=0):
        img = self.grab_screen()
        if self.run_engine:
            self.engine.forward(img)


def run_payload(cpu_pct, e2e_p50):
    payload = {"cpu": {}, "throughput": {}, "timing_ms": {}}
    for _, path in benchmark_real.SUMMARY_ROWS:
        node = payload
        for key in path[:-1]:
            node = node.setdefault(key, {})
        node[path[-1]] = 1.0
    payload["cpu"]["process_pct"] = cpu_pct
    payload["timing_ms"]["end_to_end"]["p50"] = e2e_p50
    return payload


class StatsTest(unittest.TestCase):
    def test_percentile_interpolates_between_samples(self):
        self.assertEqual(benchmark_real.percentile([1.0, 2.0, 3.0, 4.0], 50), 2.5)
        self.assertEqual(benchmark_real.percentile([5.0], 95), 5.0)
        self.assertEqual(benchmark_real.percentile([], 95), 0.0)

    def test_summarize_ms_converts_seconds(self):
        summary = benchmark_real.summarize_ms([0.001, 0.002, 0.003])
        self.assertEqual(summary["count"], 3)
        self.assertAlmostEqual(summary["p50"], 2.0)
        self.assertAlmostEqual(summary["max"], 3.0)
        self.assertEqual(benchmark_real.summarize_ms([])["count"], 0)

    def test_summarize_runs_takes_median_across_runs(self):
        runs = [run_payload(100.0, 10.0), run_payload(120.0, 14.0), run_payload(90.0, 11.0)]
        summary = benchmark_real.summarize_runs(runs)
        self.assertEqual(summary["CPU process % (100 = 1 core)"], {"median": 100.0, "min": 90.0, "max": 120.0})
        self.assertEqual(summary["end-to-end ms p50"]["median"], 11.0)

    def test_print_table_reports_delta_percent(self):
        before = benchmark_real.summarize_runs([run_payload(100.0, 10.0)])
        after = benchmark_real.summarize_runs([run_payload(80.0, 10.0)])
        out = io.StringIO()
        with redirect_stdout(out):
            benchmark_real.print_table(before, after, "HEAD~1", "worktree")
        cpu_line = next(line for line in out.getvalue().splitlines() if line.startswith("CPU process %"))
        self.assertTrue(cpu_line.endswith("-20.0%"))


class ConfigOverrideTest(unittest.TestCase):
    def test_set_dotted_parses_yaml_values_and_creates_sections(self):
        cfg = {"mouse": {"smooth": 0.1}}
        benchmark_real.set_dotted(cfg, "control_fps", "144")
        benchmark_real.set_dotted(cfg, "runtime.capture_fps", "240")
        benchmark_real.set_dotted(cfg, "mouse.smooth", "0.25")
        self.assertEqual(cfg, {"mouse": {"smooth": 0.25}, "control_fps": 144, "runtime": {"capture_fps": 240}})


class SnapshotTest(unittest.TestCase):
    def test_snapshot_ref_extracts_tracked_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "head"
            dest.mkdir()
            commit = benchmark_real.snapshot_ref("HEAD", dest)
            self.assertEqual(len(commit), 40)
            self.assertTrue((dest / "main.py").exists())
            self.assertTrue((dest / "inference.py").exists())
            self.assertFalse((dest / "config" / "config.yaml").exists())


class LoopProbeTest(unittest.TestCase):
    def test_records_stage_split_and_end_to_end_latency(self):
        bot = FakeMain(frame_age_s=0.003)
        probe = benchmark_real.LoopProbe()
        probe.install(bot)
        bot.forward(0)
        probe.measuring = True
        for tick in range(5):
            bot.forward(tick)

        self.assertEqual(probe.ticks, 5)
        self.assertEqual(probe.inferences, 5)
        self.assertEqual(len(probe.interval_s), 5)
        self.assertEqual(probe.invalid_timestamps, 0)
        for grab, host, infer, post, tick in zip(probe.grab_s, probe.engine_host_s, probe.infer_s, probe.post_s, probe.tick_s):
            self.assertGreaterEqual(infer, 0.002)
            self.assertGreaterEqual(host, 0.0)
            self.assertAlmostEqual(grab + host + infer + post, tick, places=9)
        for age, e2e, tick in zip(probe.age_at_grab_s, probe.e2e_s, probe.tick_s):
            self.assertGreaterEqual(age, 0.003)
            self.assertGreater(e2e, age)

    def test_skips_timings_outside_measure_window_and_without_engine(self):
        bot = FakeMain(cam_type="mss")
        bot.run_engine = False
        probe = benchmark_real.LoopProbe()
        probe.install(bot)
        bot.forward(0)
        self.assertEqual(probe.ticks, 0)

        probe.measuring = True
        bot.forward(1)
        self.assertEqual(probe.ticks, 1)
        self.assertEqual(probe.inferences, 0)
        self.assertEqual(probe.e2e_s, [])

    def test_flags_frame_timestamps_from_another_clock(self):
        bot = FakeMain(frame_age_s=-10.0)
        probe = benchmark_real.LoopProbe()
        probe.install(bot)
        probe.measuring = True
        bot.forward(0)
        self.assertEqual(probe.invalid_timestamps, 1)
        self.assertEqual(probe.e2e_s, [])


class InstanceAttrTest(unittest.TestCase):
    def test_reads_instance_dict_only(self):
        bot = FakeMain()
        self.assertIs(benchmark_real.instance_attr(bot, "cam"), bot.cam)
        self.assertIsNone(benchmark_real.instance_attr(bot, "missing"))
        self.assertIsNone(benchmark_real.instance_attr(bot, "forward"))


if __name__ == "__main__":
    unittest.main()
