"""Discovery, parsing and SAFE normalisation of MCP client configs.

Redaction happens here, at parse time: env values, full argument lists and
URL credentials/query strings are never stored on the records this module
returns, so no later code (checks, reports, CLI) can leak them.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

# Filenames recognised when a directory (or a default root) is scanned.
KNOWN_FILENAMES = ("mcp.json", ".mcp.json", ".claude.json")
KNOWN_SUFFIX_PATHS = (".cursor/mcp.json", ".vscode/mcp.json")

_SECRETISH = re.compile(r"(token|secret|key|password|passwd|auth|credential)", re.I)
_PATH_EXTS = (".js", ".mjs", ".cjs", ".ts", ".py", ".json", ".sh", ".rb", ".jar")


@dataclass
class Server:
    name: str
    config_path: str
    client: str = "generic"
    scope: str = ""               # e.g. "projects.<dir>" for Claude Code nesting
    transport: str = "unknown"    # stdio | http | sse | unknown
    command_basename: str = ""
    command_raw: str = ""         # internal only for checks; never reported raw
    args_count: int = 0
    referenced_paths: list = field(default_factory=list)  # path-like args / cwd
    broad_path_args: list = field(default_factory=list)   # args equal to / ~ .. /*
    cwd: str = ""
    env_keys: list = field(default_factory=list)          # NAMES only
    env_wildcard: bool = False    # an env value was a bare "*" (value discarded)
    allow_wildcard: bool = False  # alwaysAllow / autoApprove contains "*"
    url_host: str = ""
    disabled: bool = False
    is_filesystem: bool = False

    def inventory(self) -> dict:
        """The only representation reports may use. No env values, no args."""
        return {
            "name": self.name,
            "config_path": self.config_path,
            "client": self.client,
            "scope": self.scope,
            "transport": self.transport,
            "command": self.command_basename,
            "args_count": self.args_count,
            "referenced_paths": list(self.referenced_paths),
            "cwd": self.cwd,
            "env_keys": list(self.env_keys),
            "env": {k: "present" for k in self.env_keys},
            "url_host": self.url_host,
            "disabled": self.disabled,
        }


@dataclass
class ConfigScan:
    path: str
    client: str
    status: str                   # ok | parse-error | missing
    servers: list = field(default_factory=list)
    parse_issue: str = ""         # issue code only (PARSE-ERROR), never content


def client_for_path(path: Path) -> str:
    parts = [p.lower() for p in path.parts]
    name = path.name.lower()
    if ".cursor" in parts or "cursor" in parts:
        return "cursor"
    if ".vscode" in parts:
        return "vscode"
    if name in (".claude.json",) or ".claude" in parts or "claude" in name:
        return "claude-code"
    return "generic"


def default_config_paths(home: Path, project: Path) -> list[Path]:
    """Default local paths (PLAN.md list). Caller filters by existence."""
    return [
        home / ".claude.json",
        home / ".claude" / "settings.json",
        home / ".config" / "claude" / "claude_desktop_config.json",
        home / ".cursor" / "mcp.json",
        home / ".config" / "mcp" / "mcp.json",
        home / ".mcp.json",
        project / ".mcp.json",
        project / ".claude.json",
        project / ".cursor" / "mcp.json",
        project / "mcp.json",
        project / ".vscode" / "mcp.json",
    ]


def expand_inputs(paths, home: Path, project: Path) -> tuple[list[Path], list[str]]:
    """Resolve user paths / defaults to a de-duplicated list of config files.

    Returns (files, missing_explicit) where missing_explicit holds string
    paths the user named explicitly that do not exist.
    """
    files: list[Path] = []
    missing: list[str] = []

    def add(p: Path):
        rp = p
        if rp not in files:
            files.append(rp)

    if not paths:
        for p in default_config_paths(home, project):
            if p.is_file():
                add(p)
        return files, missing

    for raw in paths:
        p = Path(raw).expanduser()
        if p.is_dir():
            for name in KNOWN_FILENAMES:
                cand = p / name
                if cand.is_file():
                    add(cand)
            for suffix in KNOWN_SUFFIX_PATHS:
                cand = p / suffix
                if cand.is_file():
                    add(cand)
            # A directory that IS e.g. ~/.cursor also matches plain mcp.json.
        elif p.is_file():
            add(p)
        else:
            missing.append(str(p))
    return files, missing


def _looks_like_path(token: str) -> bool:
    if not token or "=" in token or token.startswith("-"):
        return False
    if token in ("/", "~", "$HOME", "..", "."):
        return True
    if token.startswith(("/", "~/", "./", "../", "$HOME/")):
        return True
    if re.match(r"^[A-Za-z]:[\\/]", token):  # Windows drive path
        return True
    if "/" in token and token.lower().endswith(_PATH_EXTS):
        return True
    if token.endswith("/*"):
        return True
    return False


def _is_broad_path(token: str, home: Path) -> bool:
    t = token.strip()
    if t in ("/", "~", "$HOME", "..", "/*", "~/*", "$HOME/*"):
        return True
    if re.match(r"^[A-Za-z]:[\\/]?$", t) or t in ("C:\\", "C:/"):
        return True
    if t.endswith("/*"):
        base = t[:-2] or "/"
        return _is_broad_path(base, home)
    expanded = t.replace("$HOME", str(home)).replace("~", str(home), 1) \
        if t.startswith(("~", "$HOME")) else t
    return expanded == str(home)


def _safe_url_host(url: str) -> str:
    """Host only, per the secret rule: userinfo, port, path, query and
    fragment are all dropped, so nothing credential-shaped can ride
    along in the one URL field a report keeps."""
    try:
        return urlparse(url).hostname or ""
    except ValueError:
        return ""


def _normalise_server(name: str, raw, config_path: Path, client: str,
                      scope: str, home: Path) -> Server | None:
    if not isinstance(raw, dict):
        return Server(name=name, config_path=str(config_path), client=client,
                      scope=scope)  # EMPTY-SERVER territory; checks will flag it
    srv = Server(name=name, config_path=str(config_path), client=client, scope=scope)
    command = raw.get("command")
    url = raw.get("url") or raw.get("serverUrl") or ""
    args = raw.get("args") if isinstance(raw.get("args"), list) else []
    args = [a for a in args if isinstance(a, str)]

    if isinstance(command, str) and command:
        srv.transport = "stdio"
        srv.command_raw = command
        srv.command_basename = Path(command.replace("\\", "/")).name or command
    elif isinstance(url, str) and url:
        srv.transport = "sse" if str(raw.get("type", "")).lower() == "sse" else "http"
        srv.url_host = _safe_url_host(url)
    srv.args_count = len(args)

    base_dir = config_path.parent
    cwd_raw = raw.get("cwd")
    if isinstance(cwd_raw, str) and cwd_raw:
        srv.cwd = cwd_raw
        srv.referenced_paths.append(cwd_raw)

    haystack = " ".join([name, srv.command_basename] + args).lower()
    srv.is_filesystem = "server-filesystem" in haystack or "filesystem" in name.lower()

    for token in args:
        if _is_broad_path(token, home):
            srv.broad_path_args.append(token)
        if _looks_like_path(token) and not _SECRETISH.search(token):
            if token not in srv.referenced_paths:
                srv.referenced_paths.append(token)
        elif token in srv.broad_path_args and token not in srv.referenced_paths:
            srv.referenced_paths.append(token)
    _ = base_dir  # referenced paths resolved against config dir in checks

    env = raw.get("env")
    if isinstance(env, dict):
        srv.env_keys = sorted(str(k) for k in env.keys())
        # Values inspected ONLY for the bare-wildcard test, then discarded.
        srv.env_wildcard = any(v == "*" for v in env.values()) or "*" in env
        if "*" in srv.env_keys:
            srv.env_wildcard = True
    for key in ("alwaysAllow", "autoApprove", "always_allow"):
        lst = raw.get(key)
        if isinstance(lst, list) and "*" in lst:
            srv.allow_wildcard = True
    srv.disabled = bool(raw.get("disabled") or raw.get("disable"))
    return srv


def _collect_servers(data: dict, config_path: Path, client: str,
                     home: Path) -> tuple[list[Server], bool]:
    """Collect normalised servers; also report a malformed container.

    A present-but-non-object server container (``mcpServers: [...]``)
    is a PARSE-ERROR per PLAN.md, not a silent "no servers": the caller
    flags the config while still keeping any servers collected from
    well-formed containers in the same file (recovery, not abort).
    Returns (servers, bad_container).
    """
    servers: list[Server] = []
    bad_container = False

    def take(container, scope: str):
        nonlocal bad_container
        if not isinstance(container, dict):
            bad_container = True
            return
        for name, raw in container.items():
            srv = _normalise_server(str(name), raw, config_path, client, scope, home)
            if srv is not None:
                servers.append(srv)

    for key in ("mcpServers", "servers"):
        if key in data:
            take(data.get(key), "")
    projects = data.get("projects")
    if isinstance(projects, dict):  # Claude Code per-project nesting
        for proj, cfg in projects.items():
            if isinstance(cfg, dict):
                for key in ("mcpServers", "servers"):
                    if key in cfg:
                        take(cfg.get(key), f"projects.{proj}")
    return servers, bad_container


def scan_config(path: Path, home: Path) -> ConfigScan:
    client = client_for_path(path)
    scan = ConfigScan(path=str(path), client=client, status="ok")
    try:
        # utf-8-sig: tolerate a BOM (common in editor-written configs)
        # while reading plain UTF-8 unchanged.
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        data = json.loads(text)
    except (OSError, ValueError):
        scan.status = "parse-error"
        scan.parse_issue = "PARSE-ERROR"
        return scan
    if not isinstance(data, dict):
        scan.status = "parse-error"
        scan.parse_issue = "PARSE-ERROR"
        return scan
    servers, bad_container = _collect_servers(data, path, client, home)
    scan.servers = servers
    if bad_container:
        # PARSE-ERROR finding (raised in checks from this status), but
        # the well-formed containers in the same file were still read.
        scan.status = "parse-error"
        scan.parse_issue = "PARSE-ERROR"
    return scan


def scan_configs(files: list[Path], home: Path) -> list[ConfigScan]:
    return [scan_config(p, home) for p in files]
