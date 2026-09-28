import argparse

from test.benchmark_protocol import golden_from_benchmark, run_synthetic_benchmark, write_json, write_replay_source


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Capture replay sources, golden outputs, and CPU benchmark artifacts.")
    parser.add_argument("--cfg", required=True, help="Path to the YAML config used for the benchmark protocol.")
    parser.add_argument("--duration", required=True, type=float, help="Requested benchmark duration in seconds.")
    parser.add_argument("--mode", choices=("no-gui", "gui"), default="no-gui", help="Benchmark mode.")
    parser.add_argument("--source", help="Replay source .npz to reuse.")
    parser.add_argument("--capture-source", action="store_true", help="Write a deterministic replay source .npz.")
    parser.add_argument("--capture-golden", action="store_true", help="Write a deterministic golden-output JSON artifact.")
    parser.add_argument("--stress", choices=("capture_overrun", "capture_failure"), help="Optional stress scenario.")
    parser.add_argument("--output", required=True, help="Output artifact path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.capture_source:
        metadata = write_replay_source(args.output, args.cfg, args.duration)
        print(f"wrote replay source: {args.output} ({metadata['frame_count']} frames)")
        return 0
    if args.capture_golden:
        payload = golden_from_benchmark(args.cfg, args.duration, args.source)
        write_json(args.output, payload)
        print(f"wrote golden output: {args.output} ({len(payload['samples'])} samples)")
        return 0
    payload = run_synthetic_benchmark(args.cfg, args.duration, args.mode, args.source, args.stress)
    write_json(args.output, payload)
    print(f"wrote benchmark: {args.output} ({payload['iterations']} iterations)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
