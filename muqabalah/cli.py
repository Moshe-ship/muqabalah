"""muqabalah CLI."""

from __future__ import annotations
import argparse
import json
import sys
from typing import Optional

from muqabalah.core import (
    balance, unbalance,
    CancellationContext, CancellationTrace,
    CancellationConflict,
)


def _load_context(path: Optional[str]) -> CancellationContext:
    if path is None:
        return CancellationContext()
    with open(path) as f:
        d = json.load(f)
    return CancellationContext(
        user_normalizations=d.get("user_normalizations") or {},
        contradiction_predicates=[tuple(p) for p in d.get("contradiction_predicates") or []],
    )


def cmd_balance(args: argparse.Namespace) -> int:
    if args.prompt is None:
        prompt = sys.stdin.read()
    else:
        prompt = args.prompt
    ctx = _load_context(args.context)

    try:
        result = balance(prompt, ctx)
    except CancellationConflict as e:
        sys.stderr.write(f"CONFLICT: {e}\n")
        sys.stderr.write(json.dumps(e.conflicts, indent=2))
        sys.stderr.write("\n")
        return 2

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
        return 0

    print(result.output)
    if args.trace:
        sys.stderr.write("\n--- trace ---\n")
        sys.stderr.write(result.trace.to_json())
        sys.stderr.write("\n")
    return 0


def cmd_unbalance(args: argparse.Namespace) -> int:
    if args.output is None:
        output = sys.stdin.read()
    else:
        output = args.output

    if not args.trace_file:
        sys.stderr.write("unbalance requires --trace-file\n")
        return 1
    with open(args.trace_file) as f:
        trace = CancellationTrace.from_json(f.read())

    original = unbalance(output, trace)
    print(original)
    return 0


def cmd_roundtrip(args: argparse.Namespace) -> int:
    if args.prompt is None:
        prompt = sys.stdin.read()
    else:
        prompt = args.prompt
    ctx = _load_context(args.context)

    try:
        result = balance(prompt, ctx)
    except CancellationConflict as e:
        sys.stderr.write(f"CONFLICT (no roundtrip possible): {e}\n")
        return 2

    recovered = unbalance(result.output, result.trace)
    if recovered == prompt:
        if args.verbose:
            print(f"Roundtrip OK ({len(result.trace.entries)} cancellations).")
        return 0
    sys.stderr.write("Roundtrip FAILED.\n")
    sys.stderr.write(f"Input:    {prompt!r}\n")
    sys.stderr.write(f"Output:   {result.output!r}\n")
    sys.stderr.write(f"Recovered:{recovered!r}\n")
    return 1


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="muqabalah",
        description="Reversible prompt-context cancellation and normalization.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    pb = sub.add_parser("balance", help="Balance a prompt (canonicalize).")
    pb.add_argument("--prompt", help="Prompt text (or stdin).")
    pb.add_argument("--context", help="JSON context file.")
    pb.add_argument("--trace", action="store_true",
                    help="Emit trace to stderr.")
    pb.add_argument("--json", action="store_true",
                    help="Emit full result as JSON.")
    pb.set_defaults(func=cmd_balance)

    pu = sub.add_parser("unbalance", help="Reverse a balance to original.")
    pu.add_argument("--output", help="Output text (or stdin).")
    pu.add_argument("--trace-file", required=True,
                    help="Trace JSON file.")
    pu.set_defaults(func=cmd_unbalance)

    pr = sub.add_parser("roundtrip",
                        help="Verify balance→unbalance recovers original.")
    pr.add_argument("--prompt", help="Prompt text (or stdin).")
    pr.add_argument("--context", help="JSON context file.")
    pr.add_argument("-v", "--verbose", action="store_true")
    pr.set_defaults(func=cmd_roundtrip)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
