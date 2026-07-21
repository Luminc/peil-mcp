# Peil MCP server

<!-- Ownership proof for the official MCP registry: it fetches
     https://pypi.org/pypi/peil-mcp/json and requires this exact line in the
     README (which PyPI serves as the package description) to match the `name`
     in server.json. Do not remove or reword it. -->

mcp-name: app.peil/peil-mcp

Connect Peil to Claude (or any MCP client): log hours, draft invoices from
unbilled hours, and check where you stand — from a prompt.

- **Docs:** https://peil.app/en/docs/mcp
- **Source:** https://github.com/Luminc/peil-mcp

The server is a pure client of Peil's public API. It authenticates with a
**scoped API key** you create in Peil under **Settings → Developer** (Pro).

## Draft-by-default

`draft_invoice` only ever creates a **draft** — nothing is sent to your
clients. Sending is a separate tool (`send_invoice`) that also requires the
separate **invoices:send** permission on your key. A key without that
permission can never email anything on your behalf.

## Tools

**Reads** (`read`)

| Tool | What it does |
|---|---|
| `list_clients` | List your clients |
| `get_client_details` | One client's details, incl. whether a default rate is set |
| `list_unbilled` | Unbilled hours per client for a period |
| `list_invoices` | List invoices, filterable by status / client |
| `orientation_snapshot` | Outstanding / overdue / drafts / YTD position |
| `get_reminder_copy` | Your custom reminder email copy + schedule |

**Hours** (`timesheet:write`)

| Tool | What it does |
|---|---|
| `log_hours` | Add a timesheet entry (client default rate unless given) |
| `edit_hours` | Edit an entry (only the fields you pass change) |
| `delete_hours` | Delete an entry (blocked if on a sent/paid invoice) |

**Clients** (`clients:write`)

| Tool | What it does |
|---|---|
| `create_client` / `update_client` / `delete_client` | Client CRUD (delete blocked if it has projects/sent invoices) |

**Invoices** (`invoices:write`)

| Tool | What it does |
|---|---|
| `draft_invoice` | Draft an invoice from unbilled hours (summary / by_project / per_day) |
| `set_invoice_status` | Change status (e.g. mark paid) — does **not** email anyone |
| `update_invoice` | Edit safe fields (due date, payment date, notes) |
| `delete_invoice` / `archive_invoice` | Delete (paid ones blocked) / archive |
| `set_reminder_copy` | Write custom reminder email copy for one tone/language |

**Client-facing email** (`invoices:send` — irreversible, always confirm first)

| Tool | What it does |
|---|---|
| `send_invoice` | Email an invoice to the client now |
| `schedule_send` | Schedule a draft to be emailed at a future time |
| `cancel_scheduled_send` | Cancel a scheduled send |
| `send_reminder` | Email a payment reminder for a sent/overdue invoice |

---

## 1. Create your key

In Peil: **Settings → Developer** → create a key with the permissions you want.
Start with **read + Log hours + Draft invoices**; leave **Send invoices** off
unless you truly want an assistant emailing clients. You'll paste this key into
your assistant's config as `PEIL_API_KEY` below.

## 2. Install the server

**The easy way — no clone, no install** (once `peil-mcp` is published to PyPI):

```sh
uvx peil-mcp          # runs the latest release on demand
# or, with pipx:
pipx run peil-mcp
```

→ Your launch command is `uvx peil-mcp` (or `pipx run peil-mcp`). Skip to
[step 3](#3-connect-your-assistant). Everything below is only needed if you're
running **from source** (e.g. before the first release, or to hack on it).

### From source

You need **Python 3.11 or newer** and a local copy of this `mcp-server/` folder.
Check your Python with `python3 --version`.

> **Which method?** Run `which uv pipx` first. If you already have `uv`, use A —
> it's the least work. If not, `pipx` (B) gives you a clean global command. If
> you have neither and don't want to install tooling, the plain-`venv` path (C)
> works with nothing but the Python that's already on your machine.

Everywhere below, replace `/ABS/PATH/TO/mcp-server` with the real absolute path
to this folder (run `pwd` inside it to get it).

### A. With `uv` (no install step)

`uv` builds and runs on demand — nothing to install first:

```sh
uv run --directory /ABS/PATH/TO/mcp-server peil-mcp
```

→ Your launch command is: `uv run --directory /ABS/PATH/TO/mcp-server peil-mcp`

Don't have `uv`? `curl -LsSf https://astral.sh/uv/install.sh | sh` (macOS/Linux)
or `pip install uv`.

### B. With `pipx` (isolated global command)

`pipx` installs the server into its own isolated environment and puts a
`peil-mcp` command on your PATH:

```sh
pipx install /ABS/PATH/TO/mcp-server
```

→ Your launch command is simply: `peil-mcp`

Don't have `pipx`? `python3 -m pip install --user pipx && python3 -m pipx ensurepath`.

### C. Plain `venv` + `pip` (works with only stock Python)

No extra tooling — just the `python3` you already have:

```sh
cd /ABS/PATH/TO/mcp-server
python3 -m venv .venv
.venv/bin/pip install .
```

→ Your launch command is: `/ABS/PATH/TO/mcp-server/.venv/bin/peil-mcp`
(equivalently `/ABS/PATH/TO/mcp-server/.venv/bin/python -m peil_mcp`).

> Use a **plain** `pip install .` (not `-e`/editable) for running. An editable
> install relies on a `.pth` path hook that can silently fail to load on some
> setups, giving `ModuleNotFoundError: No module named 'peil_mcp'`. Editable is
> only needed if you're modifying the server itself — see
> [Local development](#local-development).

## 3. Connect your assistant

**The only thing that changes between assistants is where the config lives.**
Every MCP client needs the same three things:

- **command** — your launch command from step 2
- **env** — `PEIL_API_KEY` set to the key from step 1
- (optional) **`PEIL_API_URL`** — only if you're pointing at a non-production
  Peil (see [Local development](#local-development)); defaults to
  `https://api.peil.app/api/v1`.

The canonical config block (used by Claude Desktop, Cursor, Windsurf, Cline, and
most others) looks like this — `command` + `args` are just your launch command
split on spaces:

```jsonc
{
  "mcpServers": {
    "peil": {
      "command": "peil-mcp",          // or "uv", or the venv's python path
      "args": [],                     // e.g. ["run","--directory","/ABS/PATH/TO/mcp-server","peil-mcp"] for uv
      "env": { "PEIL_API_KEY": "your-key" }
    }
  }
}
```

### Claude Desktop

Edit `claude_desktop_config.json`
(macOS: `~/Library/Application Support/Claude/`,
Windows: `%APPDATA%\Claude\`), add the block above, and restart Claude Desktop.

### Claude Code (CLI)

```sh
# pipx / venv (single-command launcher):
claude mcp add peil -e PEIL_API_KEY=your-key -- peil-mcp

# uv:
claude mcp add peil -e PEIL_API_KEY=your-key -- uv run --directory /ABS/PATH/TO/mcp-server peil-mcp
```

Anything after `--` is the launch command. Verify with `claude mcp get peil`
(look for `Status: ✔ Connected`) and use `/mcp` in a session to reconnect.

### Cursor

Add the canonical block to `.cursor/mcp.json` (this project) or
`~/.cursor/mcp.json` (all projects), then enable **peil** in
**Settings → MCP**.

### Windsurf

Add the canonical block to `~/.codeium/windsurf/mcp_config.json`, then hit
**Refresh** in the Cascade MCP panel.

### Cline / Roo (VS Code)

Open the extension's **MCP Servers → Configure** panel and add the canonical
block to `cline_mcp_settings.json`.

### VS Code (native Copilot agent mode)

VS Code uses a slightly different shape — `servers` (not `mcpServers`) and an
explicit `type` — in `.vscode/mcp.json`:

```jsonc
{
  "servers": {
    "peil": {
      "type": "stdio",
      "command": "peil-mcp",
      "args": [],
      "env": { "PEIL_API_KEY": "your-key" }
    }
  }
}
```

### Any other MCP client

Give it the same **command + args + `PEIL_API_KEY` env**. The server speaks MCP
over stdio; if a client can launch a stdio command, it can run Peil.

## First prompts

Once connected, try:

- *"Where do I stand?"* → `orientation_snapshot`
- *"Log 6 hours to De Correspondent today for editing work."* → `log_hours`
- *"Draft an invoice from my unbilled hours for De Correspondent."* → `draft_invoice`

With **Send invoices** left off your key, an assistant can prepare everything
but physically cannot email a client — you send from Peil yourself.

---

## Local development

Point the server at a local backend with `PEIL_API_URL`:

```sh
PEIL_API_URL=http://localhost:8000/api/v1 PEIL_API_KEY=your-local-key peil-mcp
```

If you're modifying the server, an editable install picks up your changes
without reinstalling:

```sh
.venv/bin/pip install -e ".[dev]"
```

Tests (mocked HTTP, no backend needed — `pythonpath = ["src"]` in
`pyproject.toml` makes them independent of the install mechanism):

```sh
.venv/bin/pytest
```
