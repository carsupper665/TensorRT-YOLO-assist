import argparse
import json
import sys

from test.benchmark_protocol import ProtocolError, metric_number, read_json, validate_benchmark


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate and compare CPU benchmark artifacts.")
    parser.add_argument("--baseline", required=True, help="Baseline benchmark JSON path.")
    parser.add_argument("--candidate", help="Candidate benchmark JSON path. Defaults to baseline for validation-only use.")
    parser.add_argument("--assert-cpu-drop", type=float, help="Minimum CPU percent reduction required.")
    parser.add_argument("--assert-control-regression", type=float, help="Maximum allowed control-cadence regression percent.")
    parser.add_argument("--assert-frame-age-regression", type=float, help="Maximum allowed p95 frame-age regression percent.")
    parser.add_argument("--assert-queue-depth", type=float, help="Maximum allowed candidate queue depth.")
    parser.add_argument("--validate-only", action="store_true", help="Only validate required benchmark metric schema.")
    return parser


def percent_drop(baseline: float, candidate: float) -> float:
    if baseline <= 0:
        return 0.0 if candidate <= baseline else -100.0
    return (baseline - candidate) / baseline * 100.0


def percent_regression(baseline: float, candidate: float, lower_is_better: bool = False) -> float:
    if baseline <= 0:
        return 0.0 if candidate == baseline else 100.0
    if lower_is_better:
        return (candidate - baseline) / baseline * 100.0
    return (baseline - candidate) / baseline * 100.0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        baseline = read_json(args.baseline)
        validate_benchmark(baseline)
        candidate = read_json(args.candidate or args.baseline)
        validate_benchmark(candidate)
    except (OSError, json.JSONDecodeError, ProtocolError) as error:
        print(f"benchmark validation failed: {error}", file=sys.stderr)
        return 1

    if args.validate_only:
        print("benchmark validation passed")
        return 0

    failures: list[str] = []
    baseline_metrics = baseline["metrics"]
    candidate_metrics = candidate["metrics"]

    if args.assert_cpu_drop is not None:
        actual = percent_drop(float(baseline_metrics["cpu_percent"]), float(candidate_metrics["cpu_percent"]))
        if actual < args.assert_cpu_drop:
            failures.append(f"CPU drop {actual:.3f}% is below required {args.assert_cpu_drop:.3f}%")

    if args.assert_control_regression is not None:
        actual = percent_regression(
            float(baseline_metrics["control_cadence_hz"]),
            float(candidate_metrics["control_cadence_hz"]),
        )
        if actual > args.assert_control_regression:
            failures.append(f"control cadence regression {actual:.3f}% exceeds {args.assert_control_regression:.3f}%")

    if args.assert_frame_age_regression is not None:
        actual = percent_regression(
            metric_number(baseline_metrics["frame_age_ms"], "p95"),
            metric_number(candidate_metrics["frame_age_ms"], "p95"),
            lower_is_better=True,
        )
        if actual > args.assert_frame_age_regression:
            failures.append(f"p95 frame-age regression {actual:.3f}% exceeds {args.assert_frame_age_regression:.3f}%")

    if args.assert_queue_depth is not None:
        actual = metric_number(candidate_metrics["queue_depth"], "max")
        if actual > args.assert_queue_depth:
            failures.append(f"queue depth {actual:.3f} exceeds {args.assert_queue_depth:.3f}")

    if failures:
        print("benchmark comparison failed")
        for failure in failures:
            print(failure)
        return 1

    print("benchmark comparison passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
