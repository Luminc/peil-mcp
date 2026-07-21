#!/usr/bin/env python3
"""Fail unless the package version agrees in every place it is written.

A peil-mcp release touches four version strings, and they drift silently:

    mcp-server/pyproject.toml   [project].version
    mcp-server/server.json      .version
    mcp-server/server.json      .packages[0].version
    the git tag                 mcp-v<version>

The failure this guards against is a PARTIAL release. PyPI takes its version
from pyproject; the MCP registry takes its version from server.json and
validates the package against PyPI. Bump one and not the other and you get a
green pipeline that publishes 0.1.3 to PyPI while the registry keeps
advertising 0.1.2 to every directory that mirrors it — with nothing failing.

Usage:
    check_version.py             # cross-check the files only
    check_version.py mcp-v0.1.2  # also require the tag to match
"""

from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    with (ROOT / "pyproject.toml").open("rb") as fh:
        pyproject_version = tomllib.load(fh)["project"]["version"]

    server = json.loads((ROOT / "server.json").read_text())
    found = {
        "pyproject.toml [project].version": pyproject_version,
        "server.json .version": server["version"],
        "server.json .packages[0].version": server["packages"][0]["version"],
    }

    if len(sys.argv) > 1:
        tag = sys.argv[1]
        if not tag.startswith("mcp-v"):
            print(f"✗ tag {tag!r} does not look like mcp-v<version>", file=sys.stderr)
            return 1
        found[f"git tag {tag}"] = tag.removeprefix("mcp-v")

    distinct = set(found.values())
    width = max(len(k) for k in found)
    for source, version in found.items():
        print(f"  {source:<{width}}  {version}")

    if len(distinct) != 1:
        print(f"\n✗ version mismatch: {sorted(distinct)}", file=sys.stderr)
        print("  Bump every location above, then re-tag.", file=sys.stderr)
        return 1

    # The registry proves package ownership by matching this line in the README
    # that PyPI serves against server.json's `name`. Losing it doesn't break the
    # build, it breaks the next `mcp-publisher publish` — after PyPI has already
    # gone out, which is exactly the partial release this script exists to stop.
    readme = (ROOT / "README.md").read_text()
    expected = f"mcp-name: {server['name']}"
    if expected not in readme:
        print(f"\n✗ README.md is missing the registry ownership proof: {expected!r}", file=sys.stderr)
        return 1

    print(f"\n✓ version {distinct.pop()} consistent; ownership proof present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
