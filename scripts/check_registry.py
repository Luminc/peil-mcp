#!/usr/bin/env python3
"""Assert the live MCP registry entry serves the expected version.

The registry entry is a snapshot taken at `mcp-publisher publish` time — it
does not track PyPI or the repo. This is the post-publish confirmation that
the snapshot actually landed, so a release cannot report success while the
directories that mirror the registry keep serving the previous version.

Usage:
    check_registry.py 0.1.2
"""

from __future__ import annotations

import json
import sys
import urllib.request

SERVER_NAME = "app.peil/peil-mcp"
REGISTRY = "https://registry.modelcontextprotocol.io/v0/servers?search=peil"


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    expected = sys.argv[1]

    with urllib.request.urlopen(REGISTRY, timeout=30) as response:
        payload = json.load(response)

    for entry in payload.get("servers", []):
        # The API has wrapped the server document in a `server` key in some
        # versions and returned it flat in others; accept both.
        meta = entry.get("server", entry)
        if meta.get("name") != SERVER_NAME:
            continue
        actual = meta.get("version")
        print(f"  name:    {meta.get('name')}")
        print(f"  version: {actual}")
        print(f"  website: {meta.get('websiteUrl')}")
        print(f"  repo:    {(meta.get('repository') or {}).get('url')}")
        if actual != expected:
            print(f"\n✗ registry serves {actual}, expected {expected}", file=sys.stderr)
            return 1
        print(f"\n✓ registry serving {expected}")
        return 0

    print(f"\n✗ {SERVER_NAME} not found in the registry", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
