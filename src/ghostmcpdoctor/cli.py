"""GhostMCP Doctor CLI.

  ghostmcpdoctor scan [--config <path> ...] [--project <dir>] [--home <dir>]
                      [--out-dir <dir>] [--no-report] [--json] [paths ...]
  ghostmcpdoctor report <mcpdoctor-report.json> [--out-dir <dir>]

Read-only: scan never edits a config, never starts a server, and never
prints env values (key names, present/absent only).
Exit codes: 0 = scanned, no findings above info; 1 = warnings or errors
found; 2 = could not scan (no configs found, explicit path missing).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .reports import (build_report, exit_code_for, render_markdown,
                      write_reports)
from .scanner import expand_inputs, scan_configs


def _print_summary(report: dict) -> None:
    s = report.get("summary", {})
    print(f"ghostmcpdoctor scan: {s.get('servers_found', 0)} server(s) in "
          f"{s.get('configs_scanned', 0)} config(s), "
          f"{s.get('findings', 0)} finding(s) "
          f"(exit {report.get('exit_code', '?')})")
    for f in report.get("findings", []):
        loc = f.get("path") or f.get("config_path")
        print(f"  [{f['severity']}] {f['server'] or '(config)'} - {loc} - "
              f"{f['issue']}: {f['detail']}")
    for note in report.get("notes", []):
        print(f"  note: {note}")


def _cmd_scan(args) -> int:
    home = Path(args.home).expanduser() if args.home else Path.home()
    project = Path(args.project).expanduser() if args.project else Path.cwd()
    inputs = list(args.config or []) + list(args.paths or [])
    files, missing = expand_inputs(inputs, home, project)
    if missing:
        for m in missing:
            print(f"error: config path not found: {m}", file=sys.stderr)
        return 2
    if not files:
        print("error: no MCP config files found (defaults do not exist and "
              "no paths were supplied)", file=sys.stderr)
        return 2
    scans = scan_configs(files, home)
    report = build_report(scans, home, missing_explicit=missing)
    if not args.no_report:
        write_reports(report, args.out_dir or Path.cwd())
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        _print_summary(report)
    return int(report.get("exit_code", 2))


def _cmd_report(args) -> int:
    src = Path(args.report_json)
    try:
        report = json.loads(src.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"error: cannot read report: {exc.__class__.__name__}",
              file=sys.stderr)
        return 2
    if report.get("tool") != "ghostmcpdoctor":
        print("error: not a ghostmcpdoctor report", file=sys.stderr)
        return 2
    # Recompute the exit code from the stored findings under the same
    # rule scan uses, rather than trusting the stored value: reports
    # written before the info-only fix carry a stale code, and the
    # re-render (and its returned code) must follow the current rule.
    report["exit_code"] = exit_code_for(
        report.get("findings", []), len(report.get("configs", [])),
        fallback=report.get("exit_code", 0))
    out_dir = args.out_dir or src.parent
    json_path, md_path = write_reports(report, out_dir)
    print(f"wrote {json_path} and {md_path}")
    if args.markdown:
        print(render_markdown(report))
    return int(report.get("exit_code", 0))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="ghostmcpdoctor",
        description="Read-only auditor for local MCP / agent-client configs")
    parser.add_argument("--version", action="version",
                        version=f"ghostmcpdoctor {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("scan", help="scan MCP configs (read-only)")
    p.add_argument("paths", nargs="*", help="config files or directories")
    p.add_argument("--config", action="append",
                   help="explicit config file or directory (repeatable)")
    p.add_argument("--project", help="project root for default local paths")
    p.add_argument("--home", help="home root for default paths (testing)")
    p.add_argument("--out-dir", help="where to write mcpdoctor-report.json "
                                     "+ MCPDOCTOR.md (default: cwd)")
    p.add_argument("--no-report", action="store_true")
    p.add_argument("--json", action="store_true",
                   help="print the full (redacted) report as JSON")

    p = sub.add_parser("report", help="re-render reports from a scan JSON")
    p.add_argument("report_json")
    p.add_argument("--out-dir", help="output directory (default: report's dir)")
    p.add_argument("--markdown", action="store_true",
                   help="also print the Markdown report")

    args = parser.parse_args(argv)
    if args.command == "scan":
        return _cmd_scan(args)
    if args.command == "report":
        return _cmd_report(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
