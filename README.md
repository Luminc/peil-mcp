# Peil MCP server

Connect Peil to Claude (or any MCP client): log hours, draft invoices from
unbilled hours, and check where you stand — from a prompt.

The server is a pure client of Peil's public API. It authenticates with a
**scoped API key** you create in Peil under **Settings → Developer** (Pro).

## Draft-by-default

`draft_invoice` only ever creates a **draft** — nothing is sent to your
clients. Sending is a separate tool (`send_invoice`) that also requires the
separate **invoices:send** permission on your key. A key without that
permission can never email anything on your behalf.

## Tools

| Tool | What it does | Key permission |
|---|---|---|
| `list_clients` | List your clients | read |
| `log_hours` | Add a timesheet entry (client default rate unless given) | timesheet:write |
| `list_unbilled` | Unbilled hours per client for a period | read |
| `draft_invoice` | Draft an invoice from unbilled hours (summary / by_project / per_day) | invoices:write |
| `send_invoice` | Email an invoice to the client — explicit, irreversible | invoices:send |
| `orientation_snapshot` | Outstanding / overdue / drafts / YTD position | read |

## Setup

1. In Peil: **Settings → Developer** → create a key with the permissions you
   want (start with read + Log hours + Draft invoices; leave *Send invoices*
   off unless you truly want an assistant sending mail).
2. Configure your MCP client with the key.

### Claude Desktop (`claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "peil": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/peil-mcp", "peil-mcp"],
      "env": { "PEIL_API_KEY": "your-key" }
    }
  }
}
```

### Claude Code

```sh
claude mcp add peil -e PEIL_API_KEY=your-key -- uv run --directory /path/to/peil-mcp peil-mcp
```

### Without uv (plain venv)

```sh
cd mcp-server
python3 -m venv .venv && .venv/bin/pip install -e .
claude mcp add peil -e PEIL_API_KEY=your-key -- ./.venv/bin/python -m peil_mcp
```

## Local development

Point the server at a local backend with `PEIL_API_URL`:

```sh
PEIL_API_URL=http://localhost:8000/api/v1 PEIL_API_KEY=your-local-key peil-mcp
```

Tests (mocked HTTP, no backend needed):

```sh
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
```
