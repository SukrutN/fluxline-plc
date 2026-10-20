#!/usr/bin/env bash
# Local compile gate for program/fluxline.st.
#
# CI runs this automatically on every push; this script exists for offline
# work and for checking edits before pushing. Builds matiec once (the same
# compiler the OpenPLC runtime uses) and keeps it by default in ~/matiec.
#
# Usage:   tools/check.sh
# Env:     MATIEC_DIR - where to keep the matiec build (default: $HOME/matiec)

set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MATIEC="${MATIC_DIR:-$HOME/matiec}"
TARGET="$(mktemp -d)"

if [ ! -x "$MATIEC/iec2c" ]; then
  echo "matiec not found at $MATIEC - building it (first run only)..."
  git clone --depth 1 https://github.com/beremiz/matiec.git "$MATIEC"
  (cd "$MATIEC" && autoreconf -i && ./configure && make -j2)
fi

(cd "$MATIEC" && ./iec2c -T "$TARGET" "$ROOT/program/fluxline.st")

echo
echo "OK - fluxline.st parses and type-checks. Generated C: $TARGET"
