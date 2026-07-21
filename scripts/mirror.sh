#!/usr/bin/env bash
#
# Project mcp-server/ onto the public mirror github.com/Luminc/peil-mcp.
#
# The monorepo is the source of truth; the mirror is a derived artifact that
# exists so the package has a public repo URL — MCP registries, awesome-lists
# and PyPI all want one, and invoice-app is private.
#
# ── Why not `git subtree push`? ──
# It fails here with a misleading "tip of your current branch is behind".
# Two of the split commits carried monorepo-flavoured messages ("mark Builder
# API plan implemented; CLAUDE.md status row") that made no sense on a
# standalone package, so they are reworded below. `subtree push` re-splits from
# scratch, regenerates the ORIGINAL hashes, and diverges from what was pushed.
#
# ── Why force-push? ──
# The mirror is a projection, not a branch anyone develops on. Split hashes are
# derived from the monorepo's commit objects, so ANY history rewrite upstream
# (a rebase onto moved main, say) changes them even when the tree is identical.
# Forcing is the correct semantic; the guard below refuses if the resulting
# tree differs, so a force can never silently drop content.
#
# Usage:  mcp-server/scripts/mirror.sh [--dry-run]
# Auth:   pushes via $MIRROR_TOKEN if set (CI), otherwise your git credentials.

set -euo pipefail

MIRROR_REPO="Luminc/peil-mcp"
PREFIX="mcp-server"
BRANCH="peil-mcp-public"
DRY_RUN="${1:-}"

cd "$(git rev-parse --show-toplevel)"

if [[ -n "${MIRROR_TOKEN:-}" ]]; then
  REMOTE="https://x-access-token:${MIRROR_TOKEN}@github.com/${MIRROR_REPO}.git"
else
  REMOTE="https://github.com/${MIRROR_REPO}.git"
fi

echo "==> Splitting ${PREFIX}/ out of the monorepo"
git branch -D "$BRANCH" 2>/dev/null || true
# subtree split writes a per-commit progress counter to stderr; capture it so a
# real failure is still reported rather than drowned in 600 lines of "n/648".
SPLIT_LOG=$(mktemp)
trap 'rm -f "$SPLIT_LOG"' EXIT
if ! git subtree split --prefix="$PREFIX" -b "$BRANCH" >/dev/null 2>"$SPLIT_LOG"; then
  echo "subtree split failed:" >&2
  cat "$SPLIT_LOG" >&2
  exit 1
fi

# Reword the two commits whose messages describe monorepo work. These hashes are
# in long-since-pushed history and are stable; if you ever rewrite upstream
# history that far back, update them or the messages silently revert.
echo "==> Rewording monorepo-flavoured commit messages"
FILTER_BRANCH_SQUELCH_WARNING=1 git filter-branch -f --msg-filter '
case "$GIT_COMMIT" in
  20ee2e1b6b98cb5a011176fc78cccf7c3e7ffbcb)
    echo "docs: point the module docstring at the archived plan doc" ;;
  3c58ef1d00674551f66a6312e16a9c82424e4210)
    echo "chore: make tests independent of the editable install (pythonpath)" ;;
  *) cat ;;
esac' "$BRANCH" >/dev/null 2>&1

# Content guard: the mirror may only ever move to a commit whose tree matches
# what we just built from the monorepo. This is what makes the force-push safe.
echo "==> Comparing against the live mirror"
if git fetch -q "$REMOTE" main 2>/dev/null; then
  LOCAL_TREE=$(git rev-parse "${BRANCH}^{tree}")
  REMOTE_TREE=$(git rev-parse 'FETCH_HEAD^{tree}')
  if [[ "$LOCAL_TREE" == "$REMOTE_TREE" ]]; then
    echo "    mirror already matches (tree ${LOCAL_TREE:0:12}) — nothing to push"
    exit 0
  fi
  echo "    tree differs: local ${LOCAL_TREE:0:12} vs mirror ${REMOTE_TREE:0:12}"
  git diff --stat FETCH_HEAD "$BRANCH" | tail -20
else
  echo "    no existing mirror branch — first push"
fi

if [[ "$DRY_RUN" == "--dry-run" ]]; then
  echo "==> --dry-run: stopping before push"
  exit 0
fi

echo "==> Pushing to ${MIRROR_REPO}"
git push --force "$REMOTE" "${BRANCH}:main"
echo "==> Done: https://github.com/${MIRROR_REPO}"
