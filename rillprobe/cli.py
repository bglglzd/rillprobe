import argparse
import sys

from . import __version__
from .errors import ContractError
from .fixtures import CASES
from .report import write_report
from .runner import demo, probe


def main(argv=None):
    parser = argparse.ArgumentParser(description="AI gateway contract testing, with reproducible evidence.")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    sandbox = commands.add_parser("demo", help="Run synthetic direct/gateway HTTP fixtures (no model inference)")
    sandbox.add_argument("--fixed", action="store_true", help="Use a repaired gateway without injected faults")
    sandbox.add_argument("--case", choices=list(CASES))
    sandbox.add_argument("--output", default="reports/demo")
    live = commands.add_parser("probe", help="Exercise a real, user-selected compatible endpoint")
    live.add_argument("--base-url", required=True, help="API root, including /v1 where required")
    live.add_argument("--model", required=True)
    live.add_argument("--kind", choices=("chat", "rerank"), default="chat")
    live.add_argument("--repeat", type=int, default=1)
    live.add_argument("--key-env", help="Name of an existing credential environment variable; never the key itself")
    live.add_argument("--timeout", type=float, default=30)
    live.add_argument("--server-version", help="Independently obtained runtime/gateway version (reported as supplied)")
    live.add_argument("--output", default="reports/live")
    args = parser.parse_args(argv)
    try:
        if args.command == "demo":
            report = demo(args.fixed, args.case)
        else:
            if not 0 < args.timeout <= 300:
                raise ContractError("invalid_input", "timeout must be positive and at most 300 seconds")
            report = probe(args.base_url, args.model, args.kind, args.repeat, args.key_env,
                           args.timeout, args.server_version)
        write_report(report, args.output)
    except (ContractError, OSError) as exc:
        print(f"rillprobe: {getattr(exc, 'code', 'output_error')}: {exc}", file=sys.stderr)
        return 2
    summary = report["summary"]
    print(f"{report['mode']} / {report['scenario']}: {summary['passed']}/{summary['checks']} checks passed; "
          f"{summary['failed']} failures. Report: {args.output}/report.html")
    if report["mode"] == "synthetic" and not args.fixed:
        print(f"Injected defects detected: {summary['detected_defects']}/{summary['seeded_defects']}. "
              "Exit 1 is expected for this deliberately broken gateway.")
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
