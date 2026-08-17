#!/usr/bin/env bash
#
# Install this repository's git hooks into .git/hooks.
#
# Git deliberately does not track .git/hooks, so a fresh clone starts with no
# hooks at all. Run this once after cloning:
#
#     scripts/hooks/install.sh

set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
HOOK_DIR="$(git rev-parse --git-path hooks)"

mkdir -p "$HOOK_DIR"

for hook in pre-push; do
    src="$ROOT/scripts/hooks/$hook"
    dest="$HOOK_DIR/$hook"
    [ -f "$src" ] || continue
    chmod +x "$src"
    if [ -e "$dest" ] && [ ! -L "$dest" ]; then
        echo "warning: $dest already exists and is not a symlink; leaving it alone." >&2
        continue
    fi
    ln -sf "$src" "$dest"
    echo "installed $hook -> $src"
done

echo
echo "Done. Verify with: scripts/check_public_safe.sh"
