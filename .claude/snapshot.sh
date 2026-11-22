#!/usr/bin/env bash
# Snapshot every agent worktree (committed + uncommitted + untracked) to refs, without touching the worktrees,
# then push them to origin as snapshot/<agent> branches. Safe to rerun any time.
set -u
cd "$(git rev-parse --show-toplevel)"
git worktree list --porcelain | awk '/^worktree /{print $2}' | grep '/.claude/worktrees/' | while read -r w; do
  name=$(basename "$w")
  idx=$(mktemp -u)
  head=$(git -C "$w" rev-parse HEAD)
  git -C "$w" ls-files -z >/dev/null
  cp "$(git -C "$w" rev-parse --git-path index)" "$idx" 2>/dev/null
  tree=$(GIT_INDEX_FILE="$idx" git -C "$w" add -A >/dev/null 2>&1; GIT_INDEX_FILE="$idx" git -C "$w" write-tree)
  rm -f "$idx"
  commit=$(git -C "$w" -c user.name=snapshot -c user.email=snapshot@local commit-tree "$tree" -p "$head" -m "WIP snapshot $name")
  git update-ref "refs/snapshots/$name" "$commit"
  git push -q origin "refs/snapshots/$name:refs/heads/snapshot/$name" --force 2>&1 | tail -1
  echo "snapshot $name -> $(git rev-parse --short "$commit")"
done
