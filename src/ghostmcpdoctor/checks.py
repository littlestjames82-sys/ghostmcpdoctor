"""Checks over normalised (already redacted) server records.

Every finding is server name + path + issue only. Detail strings are built
exclusively from names, paths and issue codes - never from env values,
argument values other than referenced file paths, or file contents.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from .scanner import ConfigScan, Server

STALE_CODES = {"MISSING-COMMAND", "MISSING-FILE", "DISABLED"}
_SHELLS = {"sh", "bash", "zsh", "cmd", "cmd.exe", "powershell", "powershell.exe",
           "pwsh", "pwsh.exe"}


def finding(server: str, config_path: str, code: str, severity: str,
            detail: str, path: str = "") -> dict:
    return {
        "server": server,
        "config_path": config_path,
        "path": path,
        "issue": code,
        "severity": severity,
        "stale": code in STALE_CODES,
        "detail": detail,
    }


def _command_exists(command_raw: str) -> bool:
    if not command_raw:
        return False
    if "/" in command_raw or "\\" in command_raw:
        p = Path(command_raw).expanduser()
        return p.exists()
    return shutil.which(command_raw) is not None


def _resolve(ref: str, config_path: str, cwd: str, home: Path) -> Path:
    expanded = ref
    if expanded.startswith("$HOME"):
        expanded = str(home) + expanded[len("$HOME"):]
    p = Path(expanded).expanduser()
    if not p.is_absolute():
        base = Path(cwd).expanduser() if cwd else Path(config_path).parent
        if not base.is_absolute():
            base = Path(config_path).parent / base
        p = base / p
    return p


def check_servers(scans: list[ConfigScan], home: Path) -> list[dict]:
    findings: list[dict] = []
    all_servers: list[Server] = []
    for scan in scans:
        if scan.status == "parse-error":
            findings.append(finding("", scan.path, "PARSE-ERROR", "error",
                                    "config is not valid JSON or its server "
                                    "container is not an object"))
        all_servers.extend(scan.servers)

    # DUPLICATE: same name in 2+ definitions; flag every extra definition.
    by_name: dict[str, list[Server]] = {}
    for srv in all_servers:
        by_name.setdefault(srv.name, []).append(srv)
    for name, defs in sorted(by_name.items()):
        for extra in defs[1:]:
            detail = f"server name also defined in {defs[0].config_path}"
            # When a definition lives in a nested scope (Claude Code
            # projects.<path>), name the scope: for an in-file duplicate
            # the path alone is the same file and says nothing.
            if defs[0].scope:
                detail += f" (scope: {defs[0].scope})"
            if extra.scope:
                detail += f"; this definition is in scope: {extra.scope}"
            elif defs[0].scope:
                detail += "; this definition is at top level"
            findings.append(finding(
                name, extra.config_path, "DUPLICATE", "warn", detail))

    for srv in all_servers:
        cp = srv.config_path
        if srv.transport == "unknown":
            findings.append(finding(srv.name, cp, "EMPTY-SERVER", "error",
                                    "entry has neither a command nor a url"))
        if srv.disabled:
            findings.append(finding(srv.name, cp, "DISABLED", "info",
                                    "entry is marked disabled (stale candidate)"))
        if srv.transport == "stdio":
            if srv.command_basename.lower() in _SHELLS:
                findings.append(finding(
                    srv.name, cp, "SHELL-WRAPPER", "warn",
                    f"command is a shell ({srv.command_basename}); the real "
                    "program is hidden behind a shell invocation"))
            elif srv.command_raw and not _command_exists(srv.command_raw):
                findings.append(finding(
                    srv.name, cp, "MISSING-COMMAND", "error",
                    f"command not found: {srv.command_basename}"))
        seen_refs = set()
        for ref in srv.referenced_paths:
            if ref in seen_refs:
                continue
            seen_refs.add(ref)
            resolved = _resolve(ref, cp, srv.cwd if ref != srv.cwd else "", home)
            if ref == srv.cwd and srv.cwd:
                resolved = _resolve(ref, cp, "", home)
            if not resolved.exists():
                # Bare broad / wildcard tokens are permission findings,
                # not file checks.
                if ref in ("/", "~", "$HOME", "..", "/*") or "*" in ref:
                    continue
                findings.append(finding(
                    srv.name, cp, "MISSING-FILE", "error",
                    "referenced path does not exist", path=ref))
        if srv.broad_path_args:
            findings.append(finding(
                srv.name, cp, "BROAD-FILESYSTEM", "warn",
                "path argument grants a broad root: "
                + ", ".join(sorted(set(srv.broad_path_args))),
                path=sorted(set(srv.broad_path_args))[0]))
        if srv.env_wildcard or srv.allow_wildcard:
            which = "env" if srv.env_wildcard else "allow-list"
            findings.append(finding(
                srv.name, cp, "BROAD-ENV", "warn",
                f"wildcard ('*') present in {which} block (key names "
                "only in this report; values are never reported)"))
    findings.sort(key=lambda f: (f["config_path"], f["server"], f["issue"]))
    return findings
