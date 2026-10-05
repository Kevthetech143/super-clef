#!/usr/bin/env bash
# Link `superclef` into ~/.local/bin (or $BIN_DIR), pointing at this checkout.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
BIN_DIR="${BIN_DIR:-$HOME/.local/bin}"
mkdir -p "$BIN_DIR"
if [ -e "$BIN_DIR/superclef" ] && ! grep -q 'super-clef-installer' "$BIN_DIR/superclef" 2>/dev/null; then
  echo "$BIN_DIR/superclef exists and was not made by this installer; not overwriting it." >&2; exit 1
fi
if [ -e "$BIN_DIR/superclef" ]; then
  OLD="$(sed -n 's/^# super-clef-installer: runs the checkout at //p' "$BIN_DIR/superclef" | head -1)"
  if [ -n "$OLD" ] && [ "$OLD" != "$ROOT" ]; then
    echo "replacing the launcher for $OLD (now points at $ROOT)"
  fi
fi
cat > "$BIN_DIR/superclef" <<EOF
#!/usr/bin/env bash
# super-clef-installer: runs the checkout at $ROOT
exec node "$ROOT/bin/superclef.js" "\$@"
EOF
chmod +x "$BIN_DIR/superclef"
echo "Installed $BIN_DIR/superclef -> $ROOT"
