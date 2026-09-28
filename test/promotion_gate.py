import argparse
from pathlib import Path
from typing import Any

from test.compare_benchmark import percent_drop
from test.benchmark_protocol import metric_number, read_json, validate_benchmark

CPU_REDUCTION_TARGET_PERCENT = 30.0
HOTSPOT_AVG_MS_THRESHOLDS = {
    "timer_stat_overhead_ms": 0.05,
    "preprocess_ms": 1.0,
    "postprocess_ms": 1.0,
}


def _named_hotspots(candidate_metrics: dict[str, Any]) -> list[str]:
    hotspots: list[str] = []
    for metric_name, threshold_ms in HOTSPOT_AVG_MS_THRESHOLDS.items():
        value = metric_number(candidate_metrics[metric_name], "avg")
        if value >= threshold_ms:
            hotspots.append(metric_name)
    return hotspots


def evaluate_phase2_promotion(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    validate_benchmark(baseline)
    validate_benchmark(candidate)
    baseline_metrics = baseline["metrics"]
    candidate_metrics = candidate["metrics"]
    cpu_reduction = percent_drop(float(baseline_metrics["cpu_percent"]), float(candidate_metrics["cpu_percent"]))
    hotspots = _named_hotspots(candidate_metrics)

    if cpu_reduction >= CPU_REDUCTION_TARGET_PERCENT:
        decision = "unnecessary"
        summary = "phase 1 reached the 30% CPU reduction target; phase 2 native/C++ extraction is unnecessary"
    elif hotspots:
        decision = "eligible"
        summary = "phase 1 missed the 30% CPU reduction target and named Python hotspots remain eligible for phase 2 review"
    else:
        decision = "blocked"
        summary = "phase 1 missed the 30% CPU reduction target, but phase 2 is blocked until a named hotspot meets promotion thresholds"

    return {
        "decision": decision,
        "cpu_reduction_percent": cpu_reduction,
        "required_cpu_reduction_percent": CPU_REDUCTION_TARGET_PERCENT,
        "hotspots": hotspots,
        "hotspot_thresholds_ms": HOTSPOT_AVG_MS_THRESHOLDS.copy(),
        "summary": summary,
    }


def format_phase2_promotion_gate(decision: dict[str, Any], baseline_path: str | Path, candidate_path: str | Path) -> str:
    hotspots = ", ".join(decision["hotspots"]) if decision["hotspots"] else "none"
    thresholds = ", ".join(f"{name}>={value:g}ms avg" for name, value in decision["hotspot_thresholds_ms"].items())
    lines = [
        "Phase-2 native/C++ promotion gate",
        f"Baseline: {baseline_path}",
        f"Candidate: {candidate_path}",
        f"CPU reduction: {decision['cpu_reduction_percent']:.3f}%",
        f"Required CPU reduction: {decision['required_cpu_reduction_percent']:.3f}%",
        f"Named hotspots: {hotspots}",
        f"Hotspot thresholds: {thresholds}",
        f"Decision: {decision['decision']}",
        f"Summary: {decision['summary']}",
        "Criteria: phase 2 native/C++ extraction is unnecessary when phase 1 reaches >=30% CPU reduction; if phase 1 misses that target, phase 2 is eligible only for named hotspots meeting the thresholds above.",
    ]
    return "\n".join(lines) + "\n"


def write_phase2_promotion_gate(baseline_path: str | Path, candidate_path: str | Path, output_path: str | Path) -> dict[str, Any]:
    baseline = read_json(baseline_path)
    candidate = read_json(candidate_path)
    decision = evaluate_phase2_promotion(baseline, candidate)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(format_phase2_promotion_gate(decision, baseline_path, candidate_path), encoding="utf-8")
    return decision


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Write phase-2 native/C++ promotion gate evidence.")
    parser.add_argument("--baseline", required=True, help="Baseline benchmark JSON path.")
    parser.add_argument("--candidate", required=True, help="Candidate benchmark JSON path.")
    parser.add_argument("--output", required=True, help="Output text evidence path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    decision = write_phase2_promotion_gate(args.baseline, args.candidate, args.output)
    print(f"phase-2 promotion gate: {decision['decision']} ({decision['cpu_reduction_percent']:.3f}% CPU reduction)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
