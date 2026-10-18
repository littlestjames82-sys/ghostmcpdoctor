# Examples

Sample MCP configs for trying GhostMCP Doctor. **Every value in
these files is fake.** Env values are labelled
`FAKE-EXAMPLE-...-not-a-real-secret`, commands point at example
module names, and the one "missing" command is a deliberately
invented name. Nothing here is a real credential, a real server,
or a real path.

| File | Shape | What it shows |
|---|---|---|
| `claude-code.mcp.json` | Claude Code (`mcpServers`) | A clean config: two narrow servers, one env key (fake) reported by name only. Scans with 0 findings. |
| `cursor.mcp.json` | Cursor (`mcpServers`) | Defines `project-docs` again, the same name as in the Claude Code sample: scanning both files together reports a `DUPLICATE`. |
| `antigravity.mcp_config.json` | Generic (`mcpServers`, `mcp_config` filename) | Another client shape carrying an env key (fake) that is reported present/absent only. |
| `vscode.mcp.json` | VS Code (`servers`) | The VS Code container shape: top-level `servers`, not `mcpServers`. |
| `messy.mcp.json` | Generic (`mcpServers`) | The findings showcase: a filesystem server granted `/` under two names, a command that does not exist, and a key-holder server whose fake env values must never appear in any report. |

See [WALKTHROUGH.md](WALKTHROUGH.md) for the commands to run and
the verified output to expect.
