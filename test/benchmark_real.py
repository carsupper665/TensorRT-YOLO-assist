"""Before/after benchmark of the real main loop (capture -> TensorRT -> target -> mouse).

Each revision runs in its own subprocess that imports that revision's ``main.py`` /
``inference.py`` / ``utils`` and drives ``Main.start()`` exactly as ``start.py --no-gui``
does. Only side effects are stubbed: the serial mouse (commands are formatted but not
written) and the pynput listeners. Mouse mode is forced to AimBot with aiming held so the
engine runs every frame.

Measured per run (after warmup):
- process CPU (whole process, all threads) plus a split for loop / capture / other threads
- per-stage timings: grab (wait for new frame + copy), engine host side, TensorRT infer,
  target + mouse, whole tick
- end-to-end latency: DXGI present time of the frame -> mouse command issued (dxcam only)

dxcam only delivers a frame when the screen changes, so keep something moving in the
capture region (the game, or a video) and keep it the same for every run.

Example:
    C:/Users/admin/anaconda3/envs/cuda12/python.exe test/benchmark_real.py compare --before HEAD~1
"""

import argparse
import importlib
import io
import json
import os
import statistics
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parent.parent
WORKTREE = "WORKTREE"
DEFAULT_CUDA_LIB = r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.6\lib\x64"
CPU_SAMPLE_INTERVAL_S = 0.5
MAX_VALID_FRAME_AGE_S = 5.0
LOW_LOOP_HZ_WARNING = 30.0


# ---------------------------------------------------------------------------
# Stats helpers
# ---------------------------------------------------------------------------

def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    pos = (len(ordered) - 1) * pct / 100.0
    low = int(pos)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)


def summarize_ms(values_s: list[float]) -> dict[str, float]:
    values = [v * 1000.0 for v in values_s]
    if not values:
        return {"count": 0, "avg": 0.0, "p50": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0}
    return {
        "count": len(values),
        "avg": statistics.fmean(values),
        "p50": percentile(values, 50),
        "p95": percentile(values, 95),
        "p99": percentile(values, 99),
        "max": max(values),
    }


# ---------------------------------------------------------------------------
# Worker: runs one revision's Main.start() in this process
# ---------------------------------------------------------------------------

def instance_attr(obj: Any, name: str, default: Any = None) -> Any:
    # Main is a QObject whose __init__ is skipped in no-gui mode; missing attributes then raise
    # RuntimeError instead of AttributeError, so getattr/hasattr defaults do not work on it.
    return vars(obj).get(name, default)


class FakeMouse:
    """Stands in for utils.mouse.USBMouse; builds the same command bytes but never writes."""

    def __init__(self, device: str = ""):
        self.device = device
        self.sent = 0

    def send_mouse_move(self, dx, dy, silent=False):
        prefix = "silent" if silent else ""
        _ = f"{prefix}{int(dx)}:{int(dy)}".encode()
        self.sent += 1

    def close(self):
        pass

    def open(self):
        pass


class IdleListener:
    """Stands in for pynput listeners so the benchmark does not hook real input."""

    def __init__(self, *args, **kwargs):
        self.running = False

    def start(self):
        self.running = True

    def stop(self):
        self.running = False

    def is_alive(self):
        return self.running


class LoopProbe:
    """Wraps the instance methods Main.start() calls every tick and records timings."""

    def __init__(self):
        self.measuring = False
        self.ready = threading.Event()
        self.loop_native_id: int | None = None
        self.grab_s: list[float] = []
        self.engine_host_s: list[float] = []
        self.infer_s: list[float] = []
        self.post_s: list[float] = []
        self.tick_s: list[float] = []
        self.interval_s: list[float] = []
        self.e2e_s: list[float] = []
        self.age_at_grab_s: list[float] = []
        self.ticks = 0
        self.inferences = 0
        self.none_frames = 0
        self.invalid_timestamps = 0
        self.repeated_frames = 0
        self._prev_tick_start: float | None = None
        self._prev_frame_ts: float | None = None
        self._reset_tick()

    def _reset_tick(self):
        self._t_grab = 0.0
        self._t_engine = 0.0
        self._t_infer = 0.0
        self._frame_ts: float | None = None
        self._grab_end = 0.0
        self._got_none = False
        self._ran_engine = False

    def install(self, bot) -> None:
        perf = time.perf_counter
        cam = instance_attr(bot, "cam")
        use_timestamp = instance_attr(bot, "cam_type", "") == "dxcam" and cam is not None
        orig_grab = bot.grab_screen

        def grab():
            t0 = perf()
            if use_timestamp:
                out = cam.get_latest_frame(with_timestamp=True)
                frame, ts = (None, None) if out is None else out
            else:
                frame, ts = orig_grab(), None
            self._grab_end = perf()
            self._t_grab = self._grab_end - t0
            self._frame_ts = ts
            self._got_none = frame is None
            return frame

        bot.grab_screen = grab

        engine = bot.engine
        orig_engine_forward = engine.forward
        orig_infer = engine.infer

        def infer(img):
            t0 = perf()
            out = orig_infer(img)
            self._t_infer = perf() - t0
            return out

        def engine_forward(image, *args, **kwargs):
            t0 = perf()
            out = orig_engine_forward(image, *args, **kwargs)
            self._t_engine = perf() - t0
            self._ran_engine = True
            return out

        engine.infer = infer
        engine.forward = engine_forward

        orig_forward = bot.forward

        def forward(tick: int = 0):
            if self.loop_native_id is None:
                self.loop_native_id = threading.get_native_id()
            self._reset_tick()
            t0 = perf()
            orig_forward(tick)
            t1 = perf()
            if self.measuring:
                self._record(t0, t1)
            self._prev_tick_start = t0

        bot.forward = forward

    def _record(self, t0: float, t1: float) -> None:
        self.ticks += 1
        tick = t1 - t0
        self.tick_s.append(tick)
        if self._prev_tick_start is not None:
            self.interval_s.append(t0 - self._prev_tick_start)
        self.grab_s.append(self._t_grab)
        if self._got_none:
            self.none_frames += 1
        if self._ran_engine:
            self.inferences += 1
            self.engine_host_s.append(self._t_engine - self._t_infer)
            self.infer_s.append(self._t_infer)
            self.post_s.append(tick - self._t_grab - self._t_engine)
        ts = self._frame_ts
        if ts is not None:
            if ts == self._prev_frame_ts:
                self.repeated_frames += 1
            self._prev_frame_ts = ts
            age_at_grab = self._grab_end - ts
            e2e = t1 - ts
            if 0.0 <= age_at_grab <= MAX_VALID_FRAME_AGE_S:
                self.age_at_grab_s.append(age_at_grab)
                self.e2e_s.append(e2e)
            else:
                self.invalid_timestamps += 1


class CpuMeter:
    """Process CPU over the measurement window, with per-thread attribution and 0.5 s samples."""

    def __init__(self):
        import psutil

        self.proc = psutil.Process()
        self.logical_cores = psutil.cpu_count(logical=True) or 1
        self.samples_pct: list[float] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _threads(self) -> dict[int, float]:
        return {t.id: t.user_time + t.system_time for t in self.proc.threads()}

    def _cpu_s(self) -> float:
        times = self.proc.cpu_times()
        return times.user + times.system

    def _sample_loop(self):
        last_cpu, last_wall = self._cpu_s(), time.perf_counter()
        while not self._stop.wait(CPU_SAMPLE_INTERVAL_S):
            cpu, wall = self._cpu_s(), time.perf_counter()
            self.samples_pct.append(100.0 * (cpu - last_cpu) / max(wall - last_wall, 1e-9))
            last_cpu, last_wall = cpu, wall

    def start(self):
        self.wall0 = time.perf_counter()
        self.cpu0 = self._cpu_s()
        self.threads0 = self._threads()
        self._thread = threading.Thread(target=self._sample_loop, name="bench-cpu-sampler", daemon=True)
        self._thread.start()

    def stop(self):
        self.wall1 = time.perf_counter()
        self.cpu1 = self._cpu_s()
        self.threads1 = self._threads()
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def thread_pct(self, native_id: int | None) -> float:
        if native_id is None or native_id not in self.threads1:
            return 0.0
        used = self.threads1[native_id] - self.threads0.get(native_id, 0.0)
        return 100.0 * used / max(self.wall1 - self.wall0, 1e-9)

    def result(self, ticks: int, loop_tid: int | None, capture_tid: int | None) -> dict[str, Any]:
        wall = max(self.wall1 - self.wall0, 1e-9)
        cpu_s = self.cpu1 - self.cpu0
        total = 100.0 * cpu_s / wall
        loop = self.thread_pct(loop_tid)
        capture = self.thread_pct(capture_tid)
        return {
            "window_s": wall,
            "cpu_s": cpu_s,
            "cpu_ms_per_tick": cpu_s * 1000.0 / max(ticks, 1),
            "process_pct": total,
            "process_pct_of_machine": total / self.logical_cores,
            "logical_cores": self.logical_cores,
            "sample_p50_pct": percentile(self.samples_pct, 50),
            "sample_p95_pct": percentile(self.samples_pct, 95),
            "sample_max_pct": max(self.samples_pct) if self.samples_pct else 0.0,
            "loop_thread_pct": loop,
            "capture_thread_pct": capture,
            "other_threads_pct": max(total - loop - capture, 0.0),
        }


def set_dotted(cfg: dict, dotted_key: str, raw_value: str) -> None:
    """Apply a ``--set a.b=value`` override; the value is parsed as YAML."""
    import yaml

    node = cfg
    parts = dotted_key.split(".")
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = yaml.safe_load(raw_value)


def _shim_legacy_dxcam() -> None:
    # Pre-"new dxcam" main.py imports these at module level; dxcam 0.3.0 dropped them.
    # They are only used by the deprecated monkey-patches, which the worker disables.
    dx_module = importlib.import_module("dxcam.dxcam")
    for name in ("INFINITE", "WAIT_FAILED"):
        if not hasattr(dx_module, name):
            setattr(dx_module, name, 0xFFFFFFFF)


def run_worker(args: argparse.Namespace) -> int:
    import yaml

    os.environ["PATH"] = args.cuda_lib + os.pathsep + os.environ.get("PATH", "")
    code_dir = str(Path(args.code_dir).resolve())
    sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != SCRIPT_PATH.parent]
    sys.path.insert(0, code_dir)
    _shim_legacy_dxcam()

    with open(args.cfg, "r", encoding="utf-8") as file:
        cfg = yaml.safe_load(file) or {}
    for item in args.set or []:
        key, _, value = item.partition("=")
        set_dotted(cfg, key, value)
    # Old code would monkey-patch dxcam internals that no longer exist in dxcam 0.3.0;
    # new code ignores these flags. Force both off so both revisions use stock dxcam.
    cfg["fix_dxcam_error_hook"] = False
    cfg["fix_dxcam_thread_join"] = False

    app = importlib.import_module("main")
    common = importlib.import_module("utils.common")
    loaded_from = str(Path(app.__file__).resolve())
    if not loaded_from.startswith(code_dir):
        raise RuntimeError(f"main.py imported from {loaded_from}, expected under {code_dir}")

    app.USBMouse = FakeMouse
    app.Listener = IdleListener
    app.KB = SimpleNamespace(Listener=IdleListener)

    bot = app.Main(args=cfg, no_gui=True)
    for attr in ("cam", "engine", "m", "listener"):
        if instance_attr(bot, attr) is None:
            raise RuntimeError(f"Main.init_all() failed before creating '{attr}'; check logs/ for the error")

    mouse_mode = common.MouseMode.AimBot if args.mode == "aimbot" else common.MouseMode.Off
    probe = LoopProbe()
    orig_ensure_listeners = bot._ensure_listeners

    def ensure_listeners_then_instrument():
        # Called by start() after the camera is started and after start() resets the mode.
        orig_ensure_listeners()
        probe.install(bot)
        bot.current_mouse_mode = mouse_mode
        bot.aiming = True
        probe.ready.set()

    bot._ensure_listeners = ensure_listeners_then_instrument

    loop_error: list[BaseException] = []

    def run_loop():
        try:
            bot.start()
        except BaseException as error:  # noqa: BLE001 - reported to the orchestrator
            loop_error.append(error)

    loop_thread = threading.Thread(target=run_loop, name="bench-main-loop", daemon=True)
    loop_thread.start()
    if not probe.ready.wait(timeout=30):
        raise RuntimeError("Main.start() did not reach the main loop within 30 s")

    time.sleep(args.warmup)
    if not loop_thread.is_alive():
        raise RuntimeError(f"main loop exited during warmup: {loop_error or 'see logs/'}")

    capture_thread = getattr(bot.cam, "_DXCamera__thread", None)
    capture_tid = getattr(capture_thread, "native_id", None)
    meter = CpuMeter()
    meter.start()
    probe.measuring = True
    time.sleep(args.duration)
    probe.measuring = False
    meter.stop()
    loop_alive = loop_thread.is_alive()

    bot.running = False
    stop_event = instance_attr(bot, "_scheduler_stop_event")
    if stop_event is not None:
        stop_event.set()
    loop_thread.join(timeout=2)
    if loop_thread.is_alive() and instance_attr(bot, "cam") is not None:
        # Static screen: get_latest_frame() blocks until a new frame; stopping the camera releases it.
        bot.cam.stop()
        loop_thread.join(timeout=10)
    try:
        bot.engine.close()
    except Exception:
        pass

    measured_s = meter.wall1 - meter.wall0
    result = {
        "label": args.label,
        "code_dir": code_dir,
        "cfg": args.cfg,
        "overrides": args.set or [],
        "mode": args.mode,
        "camera": instance_attr(bot, "cam_type"),
        "warmup_s": args.warmup,
        "duration_s": measured_s,
        "loop_alive_through_window": loop_alive,
        "loop_error": repr(loop_error[0]) if loop_error else None,
        "cpu": meter.result(probe.ticks, probe.loop_native_id, capture_tid),
        "throughput": {
            "loop_hz": probe.ticks / measured_s,
            "inference_fps": probe.inferences / measured_s,
            "ticks": probe.ticks,
            "inferences": probe.inferences,
            "none_frames": probe.none_frames,
            "repeated_frames": probe.repeated_frames,
            "invalid_timestamps": probe.invalid_timestamps,
            "mouse_commands": getattr(instance_attr(bot, "m"), "sent", 0),
        },
        "timing_ms": {
            "grab": summarize_ms(probe.grab_s),
            "engine_host": summarize_ms(probe.engine_host_s),
            "trt_infer": summarize_ms(probe.infer_s),
            "target_and_mouse": summarize_ms(probe.post_s),
            "tick": summarize_ms(probe.tick_s),
            "tick_interval": summarize_ms(probe.interval_s),
            "frame_age_at_grab": summarize_ms(probe.age_at_grab_s),
            "end_to_end": summarize_ms(probe.e2e_s),
        },
    }
    Path(args.result).parent.mkdir(parents=True, exist_ok=True)
    with open(args.result, "w", encoding="utf-8") as file:
        json.dump(result, file, indent=2)
    return 0 if loop_alive else 1


# ---------------------------------------------------------------------------
# Orchestrator: snapshot revisions and run them interleaved
# ---------------------------------------------------------------------------

def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, check=True, capture_output=True, text=True).stdout.strip()


def snapshot_ref(ref: str, dest: Path) -> str:
    """Extract the tracked files of ``ref`` into ``dest``; returns the resolved commit."""
    commit = git("rev-parse", "--verify", f"{ref}^{{commit}}")
    archive = subprocess.run(["git", "archive", "--format=tar", commit], cwd=REPO_ROOT, check=True, capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(dest)
    if not (dest / "main.py").exists():
        raise RuntimeError(f"{ref} has no main.py")
    return commit


def resolve_code_dir(ref: str, tmp_root: Path, name: str) -> tuple[Path, str]:
    if ref == WORKTREE:
        dirty = bool(git("status", "--porcelain", "--untracked-files=no"))
        return REPO_ROOT, f"{git('rev-parse', 'HEAD')}{' + uncommitted changes' if dirty else ''}"
    dest = tmp_root / name
    dest.mkdir(parents=True)
    return dest, snapshot_ref(ref, dest)


def run_one(args: argparse.Namespace, label: str, code_dir: Path, result_path: Path) -> dict[str, Any]:
    cmd = [
        args.python, str(SCRIPT_PATH), "worker",
        "--label", label,
        "--code-dir", str(code_dir),
        "--cfg", args.cfg,
        "--duration", str(args.duration),
        "--warmup", str(args.warmup),
        "--mode", args.mode,
        "--cuda-lib", args.cuda_lib,
        "--result", str(result_path),
    ]
    for item in args.set or []:
        cmd += ["--set", item]
    timeout = args.warmup + args.duration + 180
    proc = subprocess.run(cmd, cwd=REPO_ROOT, timeout=timeout)
    if not result_path.exists():
        raise RuntimeError(f"{label} run failed (exit {proc.returncode}); no result written")
    with open(result_path, "r", encoding="utf-8") as file:
        result = json.load(file)
    if proc.returncode != 0:
        print(f"  warning: {label} worker exited {proc.returncode} (loop error: {result.get('loop_error')})")
    return result


SUMMARY_ROWS = (
    ("CPU process % (100 = 1 core)", ("cpu", "process_pct")),
    ("CPU % of whole machine", ("cpu", "process_pct_of_machine")),
    ("CPU 0.5s-sample p95 %", ("cpu", "sample_p95_pct")),
    ("CPU ms per frame (process)", ("cpu", "cpu_ms_per_tick")),
    ("  loop thread %", ("cpu", "loop_thread_pct")),
    ("  dxcam capture thread %", ("cpu", "capture_thread_pct")),
    ("  other threads %", ("cpu", "other_threads_pct")),
    ("loop Hz", ("throughput", "loop_hz")),
    ("inference FPS", ("throughput", "inference_fps")),
    ("grab ms p50", ("timing_ms", "grab", "p50")),
    ("grab ms p95", ("timing_ms", "grab", "p95")),
    ("engine host ms p50", ("timing_ms", "engine_host", "p50")),
    ("engine host ms p95", ("timing_ms", "engine_host", "p95")),
    ("TensorRT infer ms p50", ("timing_ms", "trt_infer", "p50")),
    ("TensorRT infer ms p95", ("timing_ms", "trt_infer", "p95")),
    ("target+mouse ms p50", ("timing_ms", "target_and_mouse", "p50")),
    ("tick ms p50", ("timing_ms", "tick", "p50")),
    ("tick ms p95", ("timing_ms", "tick", "p95")),
    ("frame age at grab ms p50", ("timing_ms", "frame_age_at_grab", "p50")),
    ("end-to-end ms p50", ("timing_ms", "end_to_end", "p50")),
    ("end-to-end ms p95", ("timing_ms", "end_to_end", "p95")),
    ("end-to-end ms p99", ("timing_ms", "end_to_end", "p99")),
)


def dig(payload: dict[str, Any], path: tuple[str, ...]) -> float:
    node: Any = payload
    for key in path:
        node = node[key]
    return float(node)


def summarize_runs(runs: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    summary = {}
    for name, path in SUMMARY_ROWS:
        values = [dig(run, path) for run in runs]
        summary[name] = {
            "median": statistics.median(values),
            "min": min(values),
            "max": max(values),
        }
    return summary


def print_table(before: dict, after: dict, before_label: str, after_label: str) -> None:
    width = max(len(name) for name, _ in SUMMARY_ROWS)
    print()
    print(f"{'metric (median of runs)':<{width}}  {before_label:>14}  {after_label:>14}  {'delta':>8}")
    print("-" * (width + 42))
    for name, _ in SUMMARY_ROWS:
        b = before[name]["median"]
        a = after[name]["median"]
        delta = f"{(a - b) / b * 100.0:+.1f}%" if abs(b) > 1e-12 else "n/a"
        print(f"{name:<{width}}  {b:>14.3f}  {a:>14.3f}  {delta:>8}")


def run_compare(args: argparse.Namespace) -> int:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    output = Path(args.output or REPO_ROOT / "logs" / "benchmark_real" / f"compare-{stamp}.json")
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="bench-real-") as tmp:
        tmp_root = Path(tmp)
        before_dir, before_commit = resolve_code_dir(args.before, tmp_root, "before")
        after_dir, after_commit = resolve_code_dir(args.after, tmp_root, "after")
        print(f"before: {args.before} -> {before_commit}")
        print(f"after:  {args.after} -> {after_commit}")
        print(f"{args.runs} run(s) each, warmup {args.warmup}s + measure {args.duration}s, mode={args.mode}")
        print("Keep the capture region showing the same moving content for every run.\n")

        results: dict[str, list[dict[str, Any]]] = {"before": [], "after": []}
        for round_index in range(args.runs):
            order = ("before", "after") if round_index % 2 == 0 else ("after", "before")
            for label in order:
                code_dir = before_dir if label == "before" else after_dir
                print(f"[round {round_index + 1}/{args.runs}] running {label} ...", flush=True)
                result = run_one(args, label, code_dir, tmp_root / f"{label}-{round_index}.json")
                results[label].append(result)
                cpu = result["cpu"]["process_pct"]
                hz = result["throughput"]["loop_hz"]
                e2e = result["timing_ms"]["end_to_end"]["p50"]
                print(f"  cpu {cpu:.1f}%  loop {hz:.1f} Hz  e2e p50 {e2e:.2f} ms")
                if hz < LOW_LOOP_HZ_WARNING:
                    print(f"  warning: loop only {hz:.1f} Hz - is the capture region static? dxcam waits for screen changes.")

    summary = {label: summarize_runs(runs) for label, runs in results.items()}
    report = {
        "artifact_type": "real-loop-benchmark-compare",
        "created_at": stamp,
        "before": {"ref": args.before, "commit": before_commit},
        "after": {"ref": args.after, "commit": after_commit},
        "settings": {
            "cfg": args.cfg,
            "overrides": args.set or [],
            "mode": args.mode,
            "runs": args.runs,
            "warmup_s": args.warmup,
            "duration_s": args.duration,
            "stubs": ["serial mouse (formatted, not written)", "pynput listeners"],
            "forced_config": {"fix_dxcam_error_hook": False, "fix_dxcam_thread_join": False},
        },
        "summary": summary,
        "runs": results,
    }
    with open(output, "w", encoding="utf-8") as file:
        json.dump(report, file, indent=2)

    print_table(summary["before"], summary["after"], args.before, "worktree" if args.after == WORKTREE else args.after)
    print(f"\nwrote {output}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Benchmark the real main loop of two revisions side by side.")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--cfg", default="config/config.yaml", help="YAML config (relative to repo root).")
        p.add_argument("--duration", type=float, default=20.0, help="Measured seconds per run.")
        p.add_argument("--warmup", type=float, default=5.0, help="Seconds to run before measuring.")
        p.add_argument("--mode", choices=("aimbot", "off"), default="aimbot", help="Mouse mode forced for the run.")
        p.add_argument("--set", action="append", metavar="KEY=VALUE", help="Config override, dotted keys allowed (repeatable).")
        p.add_argument("--cuda-lib", default=DEFAULT_CUDA_LIB, help="CUDA/TensorRT DLL directory prepended to PATH.")

    compare = sub.add_parser("compare", help="Run before/after revisions interleaved and compare.")
    add_common(compare)
    compare.add_argument("--before", default="HEAD~1", help="Git ref for the 'before' code.")
    compare.add_argument("--after", default=WORKTREE, help=f"Git ref for the 'after' code ({WORKTREE} = current files).")
    compare.add_argument("--runs", type=int, default=3, help="Runs per revision (alternating order).")
    compare.add_argument("--python", default=sys.executable, help="Python interpreter for worker runs.")
    compare.add_argument("--output", help="Report JSON path (default logs/benchmark_real/compare-<time>.json).")

    worker = sub.add_parser("worker", help="Internal: benchmark one code directory.")
    add_common(worker)
    worker.add_argument("--label", required=True)
    worker.add_argument("--code-dir", required=True)
    worker.add_argument("--result", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "worker":
        return run_worker(args)
    return run_compare(args)


if __name__ == "__main__":
    raise SystemExit(main())
