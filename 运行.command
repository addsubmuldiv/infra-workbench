#!/bin/bash
# Finder double-click entry, compatible with the system Bash 3.2.
set -eu
export PATH="/opt/homebrew/bin:/usr/local/bin:${PATH:-/usr/bin:/bin:/usr/sbin:/sbin}"
ROOT_DIR="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"
if [ "$(uname -s)" != "Darwin" ]; then
  printf '%s\n' 'This launcher requires macOS. On Windows, double-click 运行.cmd.' >&2
  exit 1
fi
for candidate in python3.13 python3.12 python3.11 python3 /Library/Frameworks/Python.framework/Versions/*/bin/python3; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)' >/dev/null 2>&1; then
    exec "$candidate" "$ROOT_DIR/scripts/macos_install.py" "$@"
  fi
done
printf '%s\n' 'Python 3.11+ is required. Install Python from https://www.python.org/downloads/macos/ and double-click this file again.' >&2
if [ -t 0 ]; then read -r -p 'Press Enter to close...' _answer; fi
exit 1
