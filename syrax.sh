#!/usr/bin/env bash
# Launch SYRAX: backend core (ws://127.0.0.1:8765) + orb UI (http://localhost:3000)
#   ./syrax.sh        production UI (builds when sources changed)
#   ./syrax.sh --dev  hot-reloading dev UI
set -uo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
CFG="$ROOT/backend/config/config.toml"
PY="$ROOT/backend/.venv/bin/python"

if [[ ! -x "$PY" ]]; then
  echo "SYRAX: backend not installed. Run:" >&2
  echo "  cd backend && uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements-syrax.txt" >&2
  exit 1
fi
if [[ ! -d "$ROOT/frontend/node_modules" ]]; then
  echo "SYRAX: frontend not installed. Run: cd frontend && npm install" >&2
  exit 1
fi

# Fail fast on a broken config instead of leaving the UI running alone.
"$PY" - "$CFG" <<'PYEOF'
import sys, tomllib
try:
    cfg = tomllib.load(open(sys.argv[1], "rb"))
except FileNotFoundError:
    sys.exit("SYRAX: backend/config/config.toml is missing.")
except tomllib.TOMLDecodeError as e:
    sys.exit(f"SYRAX: config.toml is not valid TOML ({e}). Only TOML goes in that file.")
if "llm" not in cfg or "daytona" not in cfg:
    sys.exit("SYRAX: config.toml needs [llm] and [daytona]. Copy config.syrax.example.toml over it.")
PYEOF
[[ $? -eq 0 ]] || exit 1

MODE="prod"
[[ "${1:-}" == "--dev" ]] && MODE="dev"

# Refuse to start half-way when a port is already taken.
for port in 8765 3000; do
  if ss -ltnH "sport = :$port" 2>/dev/null | grep -q .; then
    owner="$(ss -ltnpH "sport = :$port" 2>/dev/null | grep -o 'users:(("[^"]*",pid=[0-9]*' | head -1 | sed 's/users:(("//; s/",pid=/ pid /')"
    echo "SYRAX: port $port is already in use${owner:+ by $owner}. Is SYRAX already running?" >&2
    exit 1
  fi
done

if [[ "$MODE" == "prod" ]]; then
  BUILD_ID="$ROOT/frontend/.next/BUILD_ID"
  if [[ ! -f "$BUILD_ID" ]] || [[ -n "$(find "$ROOT/frontend/app" "$ROOT/frontend/components" "$ROOT/frontend/lib" "$ROOT/frontend/package.json" "$ROOT/frontend/next.config.ts" -newer "$BUILD_ID" -print -quit 2>/dev/null)" ]]; then
    echo "SYRAX: building the UI (first run or sources changed)..."
    (cd "$ROOT/frontend" && npx next build >/dev/null) || { echo "SYRAX: UI build failed. Run: cd frontend && npx next build" >&2; exit 1; }
  fi
fi

# Each component runs in its own process group so shutdown takes down the
# whole tree (npx -> node -> next-server, python -> whisper threads), not
# just the top process.
pids=()
start() { setsid bash -c "$1" & pids+=($!); }
cleanup() {
  trap - EXIT INT TERM
  for p in "${pids[@]}"; do kill -TERM -- "-$p" 2>/dev/null; done
  sleep 1
  for p in "${pids[@]}"; do kill -KILL -- "-$p" 2>/dev/null; done
  wait 2>/dev/null
}
trap cleanup EXIT INT TERM

start "cd '$ROOT/backend' && exec '$PY' -m syrax.server"
if [[ "$MODE" == "dev" ]]; then
  start "cd '$ROOT/frontend' && exec npx next dev --hostname 127.0.0.1 --port 3000"
else
  start "cd '$ROOT/frontend' && exec npx next start --hostname 127.0.0.1 --port 3000"
fi

echo "SYRAX core  : ws://127.0.0.1:8765/ws"
echo "SYRAX orb UI: http://localhost:3000"

# If any part dies, take the rest down so nothing runs half-broken.
wait -n
echo "SYRAX: a component exited, shutting down." >&2
