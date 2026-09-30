#!/usr/bin/env bash
# Thin wrapper: everything lives in syrax.py (Linux, macOS, Windows).
#   ./syrax.sh                     production UI
#   ./syrax.sh --dev               hot-reloading dev UI
#   ./syrax.sh --setup             install only
#   ./syrax.sh --install-service   start at login (systemd --user / launchd)
#   ./syrax.sh --uninstall-service
#   ./syrax.sh --status
#   ./syrax.sh --gate              release gate
set -uo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
for py in "$ROOT/backend/.venv/bin/python" python3.12 python3 python; do
  if command -v "$py" >/dev/null 2>&1 || [[ -x "$py" ]]; then
    exec "$py" "$ROOT/syrax.py" "$@"
  fi
done
echo "SYRAX: python3 not found. Install Python 3.12 (or uv) and rerun." >&2
exit 1
