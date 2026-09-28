import argparse

from test.benchmark_protocol import compare_numeric, read_json


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare deterministic golden-output artifacts.")
    parser.add_argument("--baseline", required=True, help="Baseline golden-output JSON path.")
    parser.add_argument("--candidate", required=True, help="Candidate golden-output JSON path.")
    parser.add_argument("--tolerance", required=True, type=float, help="Allowed absolute numeric tolerance.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    errors = compare_numeric(read_json(args.baseline), read_json(args.candidate), args.tolerance)
    if errors:
        print("golden comparison failed")
        for error in errors[:20]:
            print(error)
        return 1
    print("golden comparison passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
