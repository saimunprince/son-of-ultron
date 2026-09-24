#!/usr/bin/env bash
# Launch SYRAX: backend core (ws://127.0.0.1:8765) + orb UI (http://localhost:3000)
#   ./syrax.sh                     production UI (builds when sources changed)
#   ./syrax.sh --dev               hot-reloading dev UI
#   ./syrax.sh --install-service   start SYRAX automatically at login (systemd --user)
#   ./syrax.sh --uninstall-service remove the login service
#   ./syrax.sh --status            show the login service status
set -uo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
UNIT_DIR="$HOME/.config/systemd/user"
UNIT="$UNIT_DIR/syrax.service"

case "${1:-}" in
  --install-service)
    mkdir -p "$UNIT_DIR"
    cat > "$UNIT" <<UNITEOF
[Unit]
Description=SYRAX, son of Ultron
After=graphical-session.target network-online.target
PartOf=graphical-session.target

[Service]
Type=simple
ExecStart=$ROOT/syrax.sh --service
Restart=on-failure
RestartSec=5
KillMode=control-group
TimeoutStopSec=20
Environment=SYRAX_OPEN_UI=1

[Install]
WantedBy=graphical-session.target
UNITEOF
    systemctl --user daemon-reload
    systemctl --user enable syrax.service
    echo "SYRAX will start automatically at your next login."
    echo "Start it now:  systemctl --user start syrax     Logs:  journalctl --user -u syrax -f"
    exit 0 ;;
  --uninstall-service)
    systemctl --user disable --now syrax.service 2>/dev/null || true
    rm -f "$UNIT"
    systemctl --user daemon-reload
    echo "SYRAX login service removed."
    exit 0 ;;
  --status)
    systemctl --user status syrax.service --no-pager
    exit $? ;;
esac
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
SERVICE=0
[[ "${1:-}" == "--dev" ]] && MODE="dev"
[[ "${1:-}" == "--service" ]] && SERVICE=1

# Refuse to start half-way when a port is already taken.
for port in 8765 3000; do
  if ss -ltnH "sport = :$port" 2>/dev/null | grep -q .; then
    owner="$(ss -ltnpH "sport = :$port" 2>/dev/null | grep -o 'users:(("[^"]*",pid=[0-9]*' | head -1 | sed 's/users:(("//; s/",pid=/ pid /')"
    # As a login service, another running SYRAX is fine: step aside quietly.
    [[ "$SERVICE" == 1 ]] && exit 0
    if systemctl --user is-active --quiet syrax.service 2>/dev/null; then
      echo "SYRAX is already running as your login service." >&2
      echo "  restart (picks up new code):  systemctl --user restart syrax" >&2
      echo "  stop:                         systemctl --user stop syrax" >&2
      echo "  logs:                         journalctl --user -u syrax -f" >&2
    else
      echo "SYRAX: port $port is already in use${owner:+ by $owner}. Is SYRAX already running?" >&2
    fi
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

# Open the UI once both servers answer (login service, or SYRAX_OPEN_UI=1).
# Disowned so `wait -n` below does not mistake it for a crashed component.
if [[ "${SYRAX_OPEN_UI:-0}" == 1 ]]; then
  (
    for _ in $(seq 1 90); do
      if curl -fs -o /dev/null http://127.0.0.1:3000 && curl -fs -o /dev/null http://127.0.0.1:8765/health; then
        xdg-open http://localhost:3000 >/dev/null 2>&1
        exit 0
      fi
      sleep 1
    done
  ) &
  disown
fi

# If any part dies, take the rest down so nothing runs half-broken.
wait -n
echo "SYRAX: a component exited, shutting down." >&2
