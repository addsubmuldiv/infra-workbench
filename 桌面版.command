#!/bin/bash
set -eu
ROOT_DIR="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
APP="$ROOT_DIR/desktop/src-tauri/target/release/bundle/macos/Infra Workbench.app"
if [ "$(uname -s)" != Darwin ]; then
  printf '%s\n' 'This launcher requires macOS.' >&2
  exit 1
fi
if [ -d "$APP" ]; then
  exec open "$APP"
fi
printf '%s\n' 'Desktop app not built. See docs/DESKTOP.md. Development: cd desktop && npm run dev' >&2
exit 1
