# Container image for the Peil MCP server.
#
# Added for Glama's listing checks, which start the server and issue an MCP
# introspection request. Note what that requires: the server must come up and
# answer tools/list WITHOUT credentials. It does — PeilClient is constructed
# lazily in get_client() on the first tool *call*, not at import — so this image
# runs fine with no PEIL_API_KEY and reports all 22 tools. Don't "fix" that
# laziness into eager construction at startup; it would break introspection for
# every client that lists tools before the user has configured a key.
#
# Normal users do not need this image. The documented install is `uvx peil-mcp`,
# which is why the README leads with that.
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
