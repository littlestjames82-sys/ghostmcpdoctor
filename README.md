# GhostMCP Doctor

**What tools are your agent clients wired to, and is any of that wiring stale, duplicated, or over-broad?**

Every agent client on a machine grows its own MCP config, and nobody
audits the union of them. Claude Code keeps servers in `~/.claude.json`
and project `.mcp.json` files, Cursor in `~/.cursor/mcp.json`, VS Code
in `.vscode/mcp.json`, and the same machine quietly accumulates the
same server defined twice and drifting apart, entries pointing at
commands uninstalled months ago, a filesystem server granted `/` once
and forgotten, and env blocks carrying credentials nobody remembers
adding. The only manual alternative is opening every config by hand,
which prints the secrets inside them into scrollback and screenshots.

GhostMCP Doctor is a **read-only** scanner for those configs. It
reports, it does not operate: it never edits, fixes, installs,
removes, or starts anything, and it does not even launch an MCP
server to test it. There is no `--fix` in v0.1, on purpose.

By Ghost Developer Studio. MIT core (see PLAN.md for the pricing
posture: free core, paid layer not decided). Zero dependencies:
Python standard library only, local-first, no network calls, no
telemetry.

Position in the Ghost stack: GhostSlice governs what an agent
*reads*, GhostVerify governs whether what it read was *enough*,
Agent Seatbelt governs what an agent *does*, GhostExposure governs
what sensitive *code* is in or out of a bundle, and GhostMCP Doctor
governs what *tools* the agent clients on this machine are wired to.

## The secret rule (non-negotiable)

Env blocks in MCP configs carry API keys and tokens, so Doctor treats
every env **value** as a secret:

- Values are discarded at parse time. They are never stored on the
  normalised server record, never written to the JSON or Markdown
  report, never printed to stdout or stderr, and never included in
  an error message. A parse error never echoes file content.
- Reports list env **key names** only, as `present` / absent. That is
  the whole report: *a key exists here*, never *what it is*.
- The same discipline applies elsewhere: full argument lists are not
  reported (only a count, plus any referenced file paths needed for
  a missing-file finding), and URL userinfo and query strings are
  stripped (only the host is kept).

This is gated by a canary test, not by good intentions: the test
fixtures plant unique fake secret strings, and the suite fails if
any of them appears in any output surface. See
`tests/test_redaction.py`.

## Install

```bash
cd ghostmcpdoctor
pip install .
ghostmcpdoctor --help
```

Or run from a checkout without installing:

```bash
PYTHONPATH=src python3 -m ghostmcpdoctor --help
```

Requires Python 3.10 or newer.

## Quickstart

```bash
# Scan configs you name explicitly (files or directories)
ghostmcpdoctor scan ~/.claude.json ~/.cursor/mcp.json ./.mcp.json

# Scan with no paths: the default local locations below are used,
# but only the ones that actually exist on this machine
ghostmcpdoctor scan

# Full redacted report as JSON on stdout
ghostmcpdoctor scan ~/.claude.json --json

# Re-render the Markdown + JSON reports from a previous scan,
# without re-scanning (safe to share: it is already redacted)
ghostmcpdoctor report mcpdoctor-report.json --out-dir ./share
```

A worked walkthrough with sample configs lives in
[`examples/`](examples/README.md).

## Commands

| Command | What it does |
|---|---|
| `ghostmcpdoctor scan [paths ...] [--config <path> ...] [--home <dir>] [--project <dir>] [--out-dir <dir>] [--json] [--no-report]` | Scan config files or directories (read-only). Explicit paths win. A directory is searched for the known filenames (`mcp.json`, `.mcp.json`, `.claude.json`, `.cursor/mcp.json`, `.vscode/mcp.json`). With no paths, the default local locations are used where they exist. Writes `mcpdoctor-report.json` + `MCPDOCTOR.md` to the output directory (default: current directory, never next to a scanned config by default) and prints a short summary: counts plus one `name - path - issue` line per finding. `--json` prints the full report to stdout instead. `--no-report` writes no files. |
| `ghostmcpdoctor report <mcpdoctor-report.json> [--out-dir <dir>] [--markdown]` | Re-render Markdown + JSON from a previous scan's JSON report without re-scanning. |

Both container shapes are understood: `mcpServers` (Claude Code,
Cursor, generic) and `servers` (VS Code), at the top level and, for
Claude Code, nested under `projects.<path>.mcpServers`.

Default locations scanned when no path is given (existing files
only): `~/.claude.json`, `~/.claude/settings.json`,
`~/.config/claude/claude_desktop_config.json`, `~/.cursor/mcp.json`,
`~/.config/mcp/mcp.json`, `~/.mcp.json`, `./.mcp.json`,
`./.claude.json`, `./.cursor/mcp.json`, `./mcp.json`,
`./.vscode/mcp.json`. `--home` and `--project` re-root those defaults.

### Findings

| Code | Severity | Meaning |
|---|---|---|
| `DUPLICATE` | warn | The same server name is defined in two or more configs, or twice in one config's scopes. One finding per extra definition. |
| `MISSING-COMMAND` | error, stale | A stdio server whose command path does not exist, or whose bare command name is not found on `PATH`. |
| `MISSING-FILE` | error, stale | An argument or `cwd` that is a file/directory path and does not exist (resolved relative to the config's directory or the entry's `cwd`). |
| `EMPTY-SERVER` | error | An entry with neither `command` nor `url`. |
| `DISABLED` | info, stale | An entry marked disabled. Reported so a human can decide to remove it; Doctor never removes it. |
| `BROAD-FILESYSTEM` | warn | A path argument grants `/`, the home directory, `~`, `$HOME`, a drive root, `..`, or a trailing `/*`. Narrow project paths are not flagged. |
| `BROAD-ENV` | warn | An env key named `*`, an env value that is a bare wildcard (checked internally, never reported), or an `alwaysAllow` / `autoApprove` list containing `*`. |
| `SHELL-WRAPPER` | warn | The command is a shell (`sh`, `bash`, `zsh`, `cmd`, `powershell`, `pwsh`): the real program is hidden behind a shell invocation, so the entry can run anything the shell can. |
| `PARSE-ERROR` | error | A discovered config is not valid JSON, or its server container is not an object. Path + issue only, no content echoed. Scanning continues with the other configs. |

`MISSING-COMMAND`, `MISSING-FILE`, and `DISABLED` are also counted
as **stale evidence** in the report summary.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Scanned, and no findings above info level. A config whose only findings are info (for example one disabled server) exits 0. |
| 1 | Warnings or errors found. A `report` re-render returns the code recomputed from the stored findings under this same rule (not the stored value verbatim), so reports written by older builds render with the corrected code. |
| 2 | Could not scan: no configs found, or an explicitly named config path does not exist. A scan that found nothing to scan never exits 0. |

## Reports

- `mcpdoctor-report.json`: tool + version, UTC timestamp, the
  configs scanned (path, client kind, server count, parse status),
  the server inventory (the safe record only: name, config path,
  client, transport, command *basename*, argument count, referenced
  paths, env key names with present/absent, URL host only, disabled
  flag), the findings (server, config path, referenced path, issue
  code, severity, stale flag, plain reason), and a summary (totals
  by severity and issue code, stale count, duplicate count).
- `MCPDOCTOR.md`: the same data as a readable report: summary,
  per-config inventory, findings.

## Limits (honest notes)

- `PATH` on the scanning machine is not `PATH` inside the client
  app, so a `MISSING-COMMAND` for a bare name is **evidence, not
  proof** the client cannot launch it. The report says so.
- Doctor reports breadth and staleness as evidence. It does not
  judge whether a server is *safe* or trustworthy beyond those
  mechanical permission checks.
- Plain JSON only in v0.1 (a UTF-8 BOM at the start of a file is
  tolerated, as editor-written configs often carry one). TOML/YAML
  configs, JSONC comment stripping, and remote registries are named
  v0.2 candidates, not silent gaps. Unknown shapes degrade to "no
  servers found in this file" or a `PARSE-ERROR`, never to a crash
  or a guessed parse. A server container that is present but not an
  object is a `PARSE-ERROR`, and the rest of the file (and the other
  files in the same scan) are still read.
- Client config formats move: Claude Code has already used both
  top-level and per-project `mcpServers`. The default location list
  is a starting point, not a hard truth; explicit paths always win.

## Tests

```bash
python3 -m pytest tests -q
```

The suite is behavioural: it drives the CLI against fixture configs
planted with a duplicate name (across two files, and across the
scopes of one file), a missing command, a missing script file, a
filesystem server granted `/`, a shell wrapper, an invalid JSON
config, a disabled-only config (pins exit 0 for info-only findings),
a non-object server container (pins the `PARSE-ERROR`), and fake
secret canaries that must never appear in any output. It also proves the read-only guarantee (fixture bytes and
mtimes unchanged after scans) and the clean-config bar (a valid,
narrow, enabled config scans with exit 0 and an empty findings
list; false positives there are a release blocker).
