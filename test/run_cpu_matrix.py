import argparse

from test.benchmark_protocol import read_json, run_synthetic_benchmark, validate_benchmark, write_json
from test.compare_benchmark import metric_number, percent_drop, percent_regression


DEFAULT_CPU_DROP = 30.0
DEFAULT_CONTROL_REGRESSION = 10.0
DEFAULT_FRAME_AGE_REGRESSION = 15.0
DEFAULT_QUEUE_DEPTH = 1.0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the CPU optimization benchmark matrix.")
    parser.add_argument("--cfg", required=True, help="Path to YAML config.")
    parser.add_argument("--source", required=True, help="Replay source .npz path.")
    parser.add_argument("--baseline", required=True, help="No-GUI baseline benchmark JSON.")
    parser.add_argument("--gui-baseline", required=True, help="GUI baseline benchmark JSON.")
    parser.add_argument("--stress-baseline", required=True, help="Capture-overrun baseline benchmark JSON.")
    parser.add_argument("--capture-failure-baseline", required=True, help="Capture-failure baseline benchmark JSON.")
    parser.add_argument("--output", required=True, help="Matrix report output JSON.")
    parser.add_argument("--duration", type=float, default=60.0, help="Duration for candidate matrix scenarios.")
    parser.add_argument("--assert-cpu-drop", type=float, default=DEFAULT_CPU_DROP, help="Minimum CPU percent reduction required.")
    parser.add_argument(
        "--assert-control-regression",
        type=float,
        default=DEFAULT_CONTROL_REGRESSION,
        help="Maximum allowed control-cadence regression percent.",
    )
    parser.add_argument(
        "--assert-frame-age-regression",
        type=float,
        default=DEFAULT_FRAME_AGE_REGRESSION,
        help="Maximum allowed p95 frame-age regression percent.",
    )
    parser.add_argument("--assert-queue-depth", type=float, default=DEFAULT_QUEUE_DEPTH, help="Maximum allowed candidate queue depth.")
    return parser


def evaluate_gates(
    baseline: dict,
    candidate: dict,
    cpu_drop_threshold: float,
    control_regression_threshold: float,
    frame_age_regression_threshold: float,
    queue_depth_threshold: float,
) -> dict:
    baseline_metrics = baseline["metrics"]
    candidate_metrics = candidate["metrics"]
    cpu_drop_actual = percent_drop(float(baseline_metrics["cpu_percent"]), float(candidate_metrics["cpu_percent"]))
    control_regression_actual = percent_regression(
        float(baseline_metrics["control_cadence_hz"]),
        float(candidate_metrics["control_cadence_hz"]),
    )
    frame_age_regression_actual = percent_regression(
        metric_number(baseline_metrics["frame_age_ms"], "p95"),
        metric_number(candidate_metrics["frame_age_ms"], "p95"),
        lower_is_better=True,
    )
    queue_depth_actual = metric_number(candidate_metrics["queue_depth"], "max")

    failures: list[str] = []
    if cpu_drop_actual < cpu_drop_threshold:
        failures.append(f"CPU drop {cpu_drop_actual:.3f}% is below required {cpu_drop_threshold:.3f}%")
    if control_regression_actual > control_regression_threshold:
        failures.append(
            f"control cadence regression {control_regression_actual:.3f}% exceeds {control_regression_threshold:.3f}%"
        )
    if frame_age_regression_actual > frame_age_regression_threshold:
        failures.append(
            f"p95 frame-age regression {frame_age_regression_actual:.3f}% exceeds {frame_age_regression_threshold:.3f}%"
        )
    if queue_depth_actual > queue_depth_threshold:
        failures.append(f"queue depth {queue_depth_actual:.3f} exceeds {queue_depth_threshold:.3f}")

    return {
        "passed": not failures,
        "failures": failures,
        "thresholds": {
            "cpu_drop_percent_min": cpu_drop_threshold,
            "control_cadence_regression_percent_max": control_regression_threshold,
            "p95_frame_age_regression_percent_max": frame_age_regression_threshold,
            "queue_depth_max": queue_depth_threshold,
        },
        "cpu_drop_percent": cpu_drop_actual,
        "control_cadence_regression_percent": control_regression_actual,
        "p95_frame_age_regression_percent": frame_age_regression_actual,
        "queue_depth_max": queue_depth_actual,
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    baselines = {
        "no_gui": read_json(args.baseline),
        "gui": read_json(args.gui_baseline),
        "capture_overrun": read_json(args.stress_baseline),
        "capture_failure": read_json(args.capture_failure_baseline),
    }
    for payload in baselines.values():
        validate_benchmark(payload)

    candidates = {
        "no_gui": run_synthetic_benchmark(args.cfg, args.duration, "no-gui", args.source, None),
        "gui": run_synthetic_benchmark(args.cfg, args.duration, "gui", args.source, None),
        "capture_overrun": run_synthetic_benchmark(args.cfg, args.duration, "no-gui", args.source, "capture_overrun"),
        "capture_failure": run_synthetic_benchmark(args.cfg, 15.0, "no-gui", args.source, "capture_failure"),
    }
    for payload in candidates.values():
        validate_benchmark(payload)

    gate_results = {
        scenario: evaluate_gates(
            baselines[scenario],
            candidates[scenario],
            args.assert_cpu_drop,
            args.assert_control_regression,
            args.assert_frame_age_regression,
            args.assert_queue_depth,
        )
        for scenario in candidates
    }
    failures = [f"{scenario}: {failure}" for scenario, result in gate_results.items() for failure in result["failures"]]

    report = {
        "schema_version": 1,
        "artifact_type": "cpu-matrix",
        "source": args.source,
        "baselines": baselines,
        "candidates": candidates,
        "gate_results": gate_results,
        "passed": not failures,
        "failures": failures,
    }
    write_json(args.output, report)
    print(f"wrote CPU matrix report: {args.output}")
    if failures:
        print("CPU matrix gates failed")
        for failure in failures:
            print(failure)
        return 1
    print("CPU matrix gates passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
