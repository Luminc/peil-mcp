# Container image for the Peil MCP server.
#
# Added for Glama's listing checks — but Glama does NOT use this file. It
# generates its own Dockerfile from a build spec held in its dashboard: clone
# the mirror at a pinned commit, install, then run `mcp-proxy -- python -m
# peil_mcp`. That image gets Python from `uv python install --default`, which
# symlinks only the interpreter, so its build step must be
# `python -m pip install --no-cache-dir --break-system-packages .` — there is no
# `pip` shim on PATH (bare `pip` exits 127), and uv marks its own interpreter
# externally-managed (plain `python -m pip` and `uv pip --system` both hit
# PEP 668). That spec is not in this repo; if a Glama build fails, fix it there.
#
# What this file is for: reproducing that check locally, and anyone who wants a
# container. Normal users need neither — the documented install is
# `uvx peil-mcp`, which is why the README leads with that.
#
# What both images share is the requirement worth protecting: the server must
# come up and answer tools/list WITHOUT credentials. It does — PeilClient is
# constructed lazily in get_client() on the first tool *call*, not at import —
# so it runs fine with no PEIL_API_KEY and reports all 22 tools. Don't "fix"
# that laziness into eager construction at startup; it would break introspection
# for every client that lists tools before the user has configured a key.
#
# Build:  docker build -t peil-mcp .
# Run:    docker run --rm -i -e PEIL_API_KEY=your-key peil-mcp
#         (-i is required: this is a stdio server, it speaks JSON-RPC on stdin.)

FROM python:3.13-slim

WORKDIR /app

# Copy only what the build backend needs, so a source-only change doesn't
# invalidate the dependency layer.
COPY pyproject.toml README.md LICENSE ./
COPY src ./src

RUN pip install --no-cache-dir .

# stdio transport: no port is exposed, and nothing is served over the network.
# The container talks to https://api.peil.app outbound only.
ENTRYPOINT ["peil-mcp"]
