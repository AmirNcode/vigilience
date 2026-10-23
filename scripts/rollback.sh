#!/usr/bin/env bash
# Roll the checkout back to a previous commit and redeploy it.
#
#   scripts/rollback.sh            # previous deployed commit (from history)
#   scripts/rollback.sh <commit>   # specific commit
#
# Only code/config and pinned image versions roll back. Home Assistant state
# (users, history DB) is NOT rolled back; if an image downgrade crosses a
# database migration, restore the matching archive with restore-config.sh.
# The checkout is left in detached HEAD; return with: git checkout main
set -euo pipefail
source "$(dirname "$0")/lib.sh"
cd "$REPO_DIR"

target="${1:-}"
if [ -z "$target" ]; then
  [ -f "$STATE_FILE" ] || die "no deploy history at $STATE_FILE; pass a commit"
  target="$(awk '/ deploy / {print $3}' "$STATE_FILE" | tail -n1)"
fi
git cat-file -e "${target}^{commit}" 2>/dev/null || die "unknown commit: $target"
[ -z "$(git status --porcelain --untracked-files=no)" ] || die "tracked files modified; refusing"

info "Rolling back to $(git log -1 --format='%h %s' "$target")"
git checkout --quiet --detach "$target"
"$REPO_DIR/scripts/deploy.sh" --no-pull
printf '%s rollback -> %s\n' "$(date -Iseconds)" "$target" >> "$STATE_FILE"
warn "Checkout is detached at ${target:0:7}. Run 'git checkout main' before the next deploy."
