"""Command line entry point: `infrapilot generate "<request>" --backend local`."""

from __future__ import annotations

import argparse
import sys
import traceback

from infrapilot.backends import get_backend
from infrapilot.pipeline import RunResult, run_generate


def exit_code_for(category: str) -> int:
    if category == "ok":
        return 0
    if category in ("backend_error", "internal_error"):
        return 2
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="infrapilot")
    sub = parser.add_subparsers(dest="command", required=True)
    gen = sub.add_parser("generate", help="turn an English request into Terraform and check it")
    gen.add_argument("request", help="what to build, in plain English")
    gen.add_argument("--backend", required=True, help="backend name from config/backends.yaml")
    gen.add_argument(
        "--no-plan", action="store_true", help="stop after validate; do not run terraform plan"
    )
    return parser


def _fmt(value, spec: str = "") -> str:
    return "-" if value is None else format(value, spec)


def print_result(result: RunResult, do_plan: bool) -> None:
    meta = result.meta
    print(f"run dir:    {result.run_dir}")
    print(f"category:   {result.category}")
    if result.category != "ok":
        print(f"detail:     {meta['category_detail']}")
    print(f"model:      {_fmt(meta['model'])} (backend: {meta['backend']})")
    print(f"tokens:     {_fmt(meta['tokens_in'])} in / {_fmt(meta['tokens_out'])} out")
    latency = _fmt(meta["latency_s"], ".1f")
    print(f"latency:    {latency}{'' if latency == '-' else 's'}")

    warnings = meta["parse_warnings"]
    if warnings:
        print(f"parse warnings ({len(warnings)}):")
        for warning in warnings:
            print(f"  - {warning}")
    else:
        print("parse warnings: none")

    validate = meta["steps"].get("validate")
    if validate is None:
        print("validate:   not run")
    else:
        print(f"validate:   {validate['error_count']} error(s), {validate['warning_count']} warning(s)")
        for diag in meta["validate_diagnostics"][:3]:
            print(f"  - [{diag['severity']}] {diag['summary']}")

    plan = meta["steps"].get("plan")
    if plan is None:
        print("plan:       skipped (--no-plan)" if not do_plan else "plan:       not run")
    elif not plan["ok"]:
        print("plan:       failed")
    elif not plan["resource_changes"]:
        print("plan:       ok, no resource changes")
    else:
        print("plan:       ok")
        for address, _mode, actions in plan["resource_changes"]:
            print(f"  - {address}: {', '.join(actions)}")


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        # Terraform messages may hold characters the Windows console encoding lacks.
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")

    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.request.strip():
        parser.error("request must not be empty")

    try:
        backend = get_backend(args.backend)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    do_plan = not args.no_plan
    try:
        result = run_generate(args.request, args.backend, do_plan=do_plan, backend=backend)
    except Exception:
        # run_generate already wrote meta.json (category internal_error); the run
        # folder is named in the traceback notes.
        traceback.print_exc()
        print("error: internal error (see traceback above)", file=sys.stderr)
        return 2

    print_result(result, do_plan)
    return exit_code_for(result.category)


if __name__ == "__main__":
    sys.exit(main())
