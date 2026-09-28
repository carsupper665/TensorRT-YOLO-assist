import json
import math
import os
import statistics
import time
from pathlib import Path
from typing import Any

import numpy as np


REQUIRED_METRICS = (
    "cpu_percent",
    "inference_fps",
    "frame_age_ms",
    "preprocess_ms",
    "postprocess_ms",
    "control_cadence_hz",
    "ui_emit_cadence_hz",
    "queue_depth",
    "timer_stat_overhead_ms",
)

BENCHMARK_SCHEMA_VERSION = 1
GOLDEN_SCHEMA_VERSION = 1
DEFAULT_REPLAY_FRAMES = 8
DEFAULT_FRAME_SIZE = 640
SYNTHETIC_FPS = 30.0
MAX_SYNTHETIC_ITERATIONS = 300
SCHEDULER_WAIT_S = 0.0005
DEFAULT_UI_PREVIEW_FPS = 20.0


class ProtocolError(ValueError):
    pass


def ensure_parent(path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)


def load_yaml_config(path: str) -> dict[str, Any]:
    try:
        import yaml
    except Exception:
        return {"_yaml_unavailable": True, "path": path}

    if not os.path.exists(path):
        return {"_missing": True, "path": path}
    with open(path, "r", encoding="utf-8") as file:
        loaded = yaml.safe_load(file) or {}
    return loaded if isinstance(loaded, dict) else {"_invalid": True, "path": path}


def config_summary(cfg: dict[str, Any]) -> dict[str, Any]:
    model = cfg.get("model", {}) if isinstance(cfg.get("model", {}), dict) else {}
    return {
        "camera": cfg.get("camera"),
        "resolution_x": cfg.get("resolution_x"),
        "resolution_y": cfg.get("resolution_y"),
        "model_file_path": model.get("file_path"),
        "model_conf": model.get("conf"),
        "label_list": model.get("label_list"),
        "enemy_list": model.get("enemy_list"),
    }


def ui_preview_target_fps(cfg: dict[str, Any]) -> float:
    runtime = cfg.get("runtime", {}) if isinstance(cfg.get("runtime", {}), dict) else {}
    target_fps = cfg.get("ui_preview_fps", runtime.get("ui_preview_fps", DEFAULT_UI_PREVIEW_FPS))
    try:
        target_fps = float(target_fps)
    except (TypeError, ValueError):
        target_fps = DEFAULT_UI_PREVIEW_FPS
    return max(target_fps, 1.0)


def make_synthetic_frames(count: int = DEFAULT_REPLAY_FRAMES, size: int = DEFAULT_FRAME_SIZE) -> np.ndarray:
    y, x = np.indices((size, size), dtype=np.uint16)
    frames = np.empty((count, size, size, 3), dtype=np.uint8)
    for index in range(count):
        frames[index, :, :, 0] = (x + index * 17) % 256
        frames[index, :, :, 1] = (y + index * 11) % 256
        frames[index, :, :, 2] = ((x // 2) + (y // 3) + index * 23) % 256
    return frames


def write_replay_source(output: str, cfg_path: str, duration: float) -> dict[str, Any]:
    cfg = load_yaml_config(cfg_path)
    frames = make_synthetic_frames()
    timestamps = np.arange(frames.shape[0], dtype=np.float64) / SYNTHETIC_FPS
    metadata = {
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "source": "synthetic-replay",
        "requested_duration_s": duration,
        "fps": SYNTHETIC_FPS,
        "frame_count": int(frames.shape[0]),
        "frame_shape": list(frames.shape[1:]),
        "config": config_summary(cfg),
        "created_at_unix": time.time(),
        "reason": "deterministic fallback for constrained CI/dev environments",
    }
    ensure_parent(output)
    np.savez_compressed(output, frames=frames, timestamps=timestamps, metadata=json.dumps(metadata, sort_keys=True))
    return metadata


def load_replay_source(path: str | None, cfg_path: str, duration: float) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    if path and os.path.exists(path):
        with np.load(path, allow_pickle=False) as data:
            frames = np.asarray(data["frames"])
            timestamps = np.asarray(data["timestamps"], dtype=np.float64)
            metadata = json.loads(str(data["metadata"]))
        return frames, timestamps, metadata

    frames = make_synthetic_frames()
    timestamps = np.arange(frames.shape[0], dtype=np.float64) / SYNTHETIC_FPS
    metadata = {
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "source": "synthetic-replay",
        "requested_duration_s": duration,
        "fps": SYNTHETIC_FPS,
        "frame_count": int(frames.shape[0]),
        "frame_shape": list(frames.shape[1:]),
        "config": config_summary(load_yaml_config(cfg_path)),
        "synthetic_fallback": True,
    }
    return frames, timestamps, metadata


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    pos = (len(ordered) - 1) * pct / 100.0
    low = math.floor(pos)
    high = math.ceil(pos)
    if low == high:
        return float(ordered[int(pos)])
    return float(ordered[low] * (high - pos) + ordered[high] * (pos - low))


def summarize(values: list[float]) -> dict[str, float]:
    if not values:
        return {"avg": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0}
    return {
        "avg": float(statistics.fmean(values)),
        "p50": percentile(values, 50),
        "p95": percentile(values, 95),
        "max": float(max(values)),
    }


def deterministic_detection(frame: np.ndarray, index: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    height, width = frame.shape[:2]
    center_x = width / 2.0 + ((index % 5) - 2) * 3.0
    center_y = height / 2.0 + ((index % 7) - 3) * 2.0
    box = np.array([[center_x - 12.0, center_y - 18.0, center_x + 12.0, center_y + 18.0]], dtype=np.float32)
    confidence = np.array([0.75 + (index % 3) * 0.01], dtype=np.float32)
    class_id = np.array([index % 2], dtype=np.float32)
    return box, confidence, class_id


def run_synthetic_benchmark(
    cfg_path: str,
    duration: float,
    mode: str,
    source: str | None,
    stress: str | None,
) -> dict[str, Any]:
    frames, timestamps, source_metadata = load_replay_source(source, cfg_path, duration)
    cfg = load_yaml_config(cfg_path)
    ui_target_fps = ui_preview_target_fps(cfg)
    ui_preview_enabled = mode == "gui"
    ui_preview_period_s = 1.0 / ui_target_fps
    next_ui_emit_at = 0.0
    iterations = max(1, min(int(duration * SYNTHETIC_FPS), MAX_SYNTHETIC_ITERATIONS))
    wall_start = time.perf_counter()
    cpu_start = time.process_time()

    preprocess_values: list[float] = []
    postprocess_values: list[float] = []
    frame_age_values: list[float] = []
    timer_values: list[float] = []
    timer_window: list[float] = []
    timer_window_total_ms = 0.0
    control_events = 0
    ui_events = 0
    queue_depth_max = 0

    for index in range(iterations):
        frame_index = index % len(frames)
        frame = frames[frame_index]
        frame_age_s = max(0.0, (index / SYNTHETIC_FPS) - float(timestamps[frame_index]))
        if stress == "capture_overrun":
            frame_age_s += 1.0 / SYNTHETIC_FPS
        elif stress == "capture_failure" and index % 4 == 0:
            frame_age_s += 2.0 / SYNTHETIC_FPS
        frame_age_values.append(frame_age_s * 1000.0)
        queue_depth_max = max(queue_depth_max, 1)

        pre_start = time.perf_counter_ns()
        sample = np.ascontiguousarray(frame.transpose(2, 0, 1), dtype=np.float32) / 255.0
        preprocess_values.append((time.perf_counter_ns() - pre_start) / 1_000_000.0)

        post_start = time.perf_counter_ns()
        boxes, confidences, classes = deterministic_detection(frame, index)
        if stress == "capture_failure" and index % 4 == 0:
            boxes = boxes[:0]
            confidences = confidences[:0]
            classes = classes[:0]
        _ = (sample.shape, boxes.shape, confidences.shape, classes.shape)
        postprocess_values.append((time.perf_counter_ns() - post_start) / 1_000_000.0)

        control_events += 1
        if ui_preview_enabled and (index / SYNTHETIC_FPS) >= next_ui_emit_at:
            ui_events += 1
            next_ui_emit_at = (index / SYNTHETIC_FPS) + ui_preview_period_s
        timer_stat_start = time.perf_counter_ns()
        synthetic_dt_ms = 1000.0 / SYNTHETIC_FPS
        if len(timer_window) == 120:
            timer_window_total_ms -= timer_window.pop(0)
        timer_window.append(synthetic_dt_ms)
        timer_window_total_ms += synthetic_dt_ms
        _ = timer_window_total_ms / len(timer_window)
        timer_values.append((time.perf_counter_ns() - timer_stat_start) / 1_000_000.0)
        time.sleep(SCHEDULER_WAIT_S)

    wall_elapsed = max(time.perf_counter() - wall_start, 1e-9)
    cpu_elapsed = max(time.process_time() - cpu_start, 0.0)
    measured_seconds = max(duration, iterations / SYNTHETIC_FPS)
    cpu_percent = min(100.0 * cpu_elapsed / wall_elapsed, 999.0)

    metrics = {
        "cpu_percent": cpu_percent,
        "inference_fps": iterations / measured_seconds,
        "frame_age_ms": summarize(frame_age_values),
        "preprocess_ms": summarize(preprocess_values),
        "postprocess_ms": summarize(postprocess_values),
        "control_cadence_hz": control_events / measured_seconds,
        "ui_emit_cadence_hz": ui_events / measured_seconds,
        "queue_depth": {"max": queue_depth_max, "p95": float(queue_depth_max), "avg": float(queue_depth_max)},
        "timer_stat_overhead_ms": summarize(timer_values),
    }
    return {
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "artifact_type": "cpu-benchmark",
        "mode": mode,
        "stress": stress,
        "cfg": cfg_path,
        "source": source,
        "source_metadata": source_metadata,
        "requested_duration_s": duration,
        "iterations": iterations,
        "measured_wall_s": wall_elapsed,
        "measured_cpu_s": cpu_elapsed,
        "synthetic_fallback": True,
        "metrics": metrics,
        "scheduler": {
            "mode": "explicit-control-cadence",
            "bounded_wait_s": SCHEDULER_WAIT_S,
            "queue_depth_bound": 1,
            "ui_preview_enabled": ui_preview_enabled,
            "ui_preview_target_fps": ui_target_fps if ui_preview_enabled else 0.0,
            "ui_preview_policy": "latest-only-throttle",
        },
    }


def write_json(path: str | Path, payload: dict[str, Any]) -> None:
    ensure_parent(path)
    with open(path, "w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2, sort_keys=True)
        file.write("\n")


def read_json(path: str | Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, dict):
        raise ProtocolError(f"{path} does not contain a JSON object")
    return payload


def validate_benchmark(payload: dict[str, Any]) -> None:
    metrics = payload.get("metrics")
    if not isinstance(metrics, dict):
        raise ProtocolError("benchmark artifact is missing metrics object")
    missing = [key for key in REQUIRED_METRICS if key not in metrics]
    if missing:
        raise ProtocolError(f"benchmark artifact missing required metrics: {', '.join(missing)}")


def metric_number(metric: Any, field: str = "avg") -> float:
    if isinstance(metric, dict):
        if field in metric:
            return float(metric[field])
        if "avg" in metric:
            return float(metric["avg"])
        if "max" in metric:
            return float(metric["max"])
    return float(metric)


def golden_from_benchmark(cfg_path: str, duration: float, source: str | None) -> dict[str, Any]:
    frames, _, source_metadata = load_replay_source(source, cfg_path, duration)
    samples = []
    count = max(1, min(int(duration * SYNTHETIC_FPS), len(frames)))
    for index in range(count):
        boxes, confidences, classes = deterministic_detection(frames[index % len(frames)], index)
        samples.append(
            {
                "frame_index": index,
                "boxes": np.round(boxes, 6).tolist(),
                "confidences": np.round(confidences, 6).tolist(),
                "classes": np.round(classes, 6).tolist(),
                "control": {"target": [float((boxes[0, 0] + boxes[0, 2]) / 2.0), float((boxes[0, 1] + boxes[0, 3]) / 2.0)]},
            }
        )
    return {
        "schema_version": GOLDEN_SCHEMA_VERSION,
        "artifact_type": "golden-output",
        "cfg": cfg_path,
        "source": source,
        "source_metadata": source_metadata,
        "samples": samples,
    }


def compare_numeric(left: Any, right: Any, tolerance: float, path: str = "$") -> list[str]:
    errors: list[str] = []
    if isinstance(left, dict) and isinstance(right, dict):
        if set(left) != set(right):
            return [f"{path}: key mismatch {sorted(left)} != {sorted(right)}"]
        for key in left:
            errors.extend(compare_numeric(left[key], right[key], tolerance, f"{path}.{key}"))
        return errors
    if isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            return [f"{path}: length mismatch {len(left)} != {len(right)}"]
        for index, (left_item, right_item) in enumerate(zip(left, right)):
            errors.extend(compare_numeric(left_item, right_item, tolerance, f"{path}[{index}]"))
        return errors
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        if abs(float(left) - float(right)) > tolerance:
            return [f"{path}: {left} != {right} within tolerance {tolerance}"]
        return []
    if left != right:
        return [f"{path}: {left!r} != {right!r}"]
    return []
