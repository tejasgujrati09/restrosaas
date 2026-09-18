#!/usr/bin/env bash
# Start, stop and inspect the whole local stack.
#
#   scripts/dev.sh up [--no-seed]   Postgres + Redis, migrations, API and the three web apps
#   scripts/dev.sh down             stop the API and web apps (add --all to stop Postgres/Redis too)
#   scripts/dev.sh status           what is running, and where
#   scripts/dev.sh logs [name]      tail logs: api | guest | staff | admin (default: all)
#   scripts/dev.sh restart          down, then up
#
# Default ports are API 8000, guest 3000, staff 3001, admin 3002. A port that is already
# taken by something else is skipped and the next free one is used; `status` shows the result.
# State lives in .run/ (git-ignored): pids, chosen ports and logs.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN="$ROOT/.run"
LOGS="$RUN/logs"
PORTS_FILE="$RUN/ports.env"
SERVICES=(api guest staff admin)

# Runtime role (subject to RLS) for the API; owner role for migrations. See README "Two database roles".
RUNTIME_DB="postgresql+asyncpg://app:app@localhost:5432/app_dev"
OWNER_DB="postgresql+asyncpg://postgres:postgres@localhost:5432/app_dev"
REDIS_URL="redis://localhost:6380/0"
# The demo owner signs in with this code in development (the API refuses it in production).
DEV_OTP="123456"

say() { printf '\033[1m%s\033[0m\n' "$*"; }
die() { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }

need() { command -v "$1" >/dev/null 2>&1 || die "$1 is required but not installed. $2"; }

port_free() { ! lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }

pick_port() {
  local p="$1"
  while ! port_free "$p"; do p=$((p + 1)); done
  echo "$p"
}

pid_file() { echo "$RUN/$1.pid"; }

is_running() {
  local f pid
  f="$(pid_file "$1")"
  [[ -f "$f" ]] || return 1
  pid="$(cat "$f")"
  kill -0 "$pid" 2>/dev/null
}

kill_tree() {
  local pid="$1" child
  for child in $(pgrep -P "$pid" 2>/dev/null || true); do kill_tree "$child"; done
  kill "$pid" 2>/dev/null || true
}

wait_for() { # name url seconds
  local name="$1" url="$2" tries="$3" i
  for ((i = 0; i < tries; i++)); do
    if curl -fsS -o /dev/null "$url" 2>/dev/null; then return 0; fi
    if ! is_running "$name"; then
      echo "--- last lines of $name.log ---" >&2
      tail -n 25 "$LOGS/$name.log" >&2 || true
      die "$name exited while starting"
    fi
    sleep 1
  done
  echo "--- last lines of $name.log ---" >&2
  tail -n 25 "$LOGS/$name.log" >&2 || true
  die "$name did not answer at $url within ${tries}s"
}

load_ports() {
  [[ -f "$PORTS_FILE" ]] || die "not started yet: run scripts/dev.sh up"
  # shellcheck disable=SC1090
  source "$PORTS_FILE"
}

start_one() { # name, working dir, command...
  local name="$1" dir="$2"
  shift 2
  # Detach fully (no inherited stdin/stdout) so callers piping this script's output never hang.
  ( cd "$dir"; nohup "$@" >"$LOGS/$name.log" 2>&1 </dev/null & echo $! >"$(pid_file "$name")" )
}

cmd_up() {
  local seed=1
  [[ "${1:-}" == "--no-seed" ]] && seed=0

  need docker "Install Docker Desktop."
  need uv "Install uv: https://docs.astral.sh/uv/"
  need pnpm "Install pnpm: https://pnpm.io/installation"
  need node "Install Node 22+."
  need curl "Install curl."
  need lsof "Install lsof."
  docker info >/dev/null 2>&1 || die "Docker is not running. Start Docker Desktop and retry."

  mkdir -p "$LOGS"
  for s in "${SERVICES[@]}"; do
    if is_running "$s"; then die "$s is already running. Use: scripts/dev.sh restart"; fi
  done

  say "1/6 Postgres and Redis"
  (cd "$ROOT" && docker compose up -d --wait postgres redis)

  say "2/6 Dependencies"
  [[ -f "$ROOT/apps/api/.env" ]] || cp "$ROOT/.env.example" "$ROOT/apps/api/.env"
  (cd "$ROOT/apps/api" && uv sync --quiet)
  [[ -d "$ROOT/node_modules" ]] && [[ -d "$ROOT/apps/guest/node_modules" ]] || (cd "$ROOT" && pnpm install --silent)

  say "3/6 Database migrations"
  (cd "$ROOT/apps/api" && DATABASE_URL="$RUNTIME_DB" MIGRATION_DATABASE_URL="$OWNER_DB" uv run alembic upgrade head 2>&1 | tail -n 2)

  say "4/6 Choosing ports"
  local api_port guest_port staff_port admin_port
  api_port="$(pick_port "${API_PORT:-8000}")"
  guest_port="$(pick_port "${GUEST_PORT:-3000}")"
  staff_port="$(pick_port "${STAFF_PORT:-3001}")"
  [[ "$staff_port" == "$guest_port" ]] && staff_port="$(pick_port $((guest_port + 1)))"
  admin_port="$(pick_port "${ADMIN_PORT:-3002}")"
  while [[ "$admin_port" == "$guest_port" || "$admin_port" == "$staff_port" ]]; do admin_port="$(pick_port $((admin_port + 1)))"; done
  cat >"$PORTS_FILE" <<PORTS
API_PORT=$api_port
GUEST_PORT=$guest_port
STAFF_PORT=$staff_port
ADMIN_PORT=$admin_port
PORTS

  say "5/6 Starting services"
  local api_url="http://localhost:$api_port"
  local cors="[\"http://localhost:$guest_port\",\"http://localhost:$staff_port\",\"http://localhost:$admin_port\"]"
  start_one api "$ROOT/apps/api" env \
    DATABASE_URL="$RUNTIME_DB" MIGRATION_DATABASE_URL="$OWNER_DB" REDIS_URL="$REDIS_URL" \
    OTP_DEV_FIXED_CODE="$DEV_OTP" CORS_ORIGINS="$cors" \
    PUBLIC_BASE_URL="http://localhost:$guest_port" STAFF_BASE_URL="http://localhost:$staff_port" \
    DYLD_FALLBACK_LIBRARY_PATH="${DYLD_FALLBACK_LIBRARY_PATH:-/opt/homebrew/lib}" \
    uv run uvicorn app.main:app --port "$api_port" --reload
  wait_for api "$api_url/health" 60

  for app in guest staff admin; do
    local port_var
    case "$app" in guest) port_var=$guest_port ;; staff) port_var=$staff_port ;; admin) port_var=$admin_port ;; esac
    start_one "$app" "$ROOT" env NEXT_PUBLIC_API_URL="$api_url" \
      pnpm --filter "$app" exec next dev --port "$port_var"
  done
  wait_for guest "http://localhost:$guest_port" 120
  wait_for staff "http://localhost:$staff_port" 120
  wait_for admin "http://localhost:$admin_port" 120

  say "6/6 Demo data"
  if [[ "$seed" == 1 ]]; then
    (cd "$ROOT/apps/api" && uv run python "$ROOT/scripts/seed_demo.py" "$api_url" "http://localhost:$staff_port")
  else
    echo "skipped (--no-seed)"
  fi

  echo
  cmd_status
}

cmd_down() {
  local s
  for s in "${SERVICES[@]}"; do
    if is_running "$s"; then
      kill_tree "$(cat "$(pid_file "$s")")"
      echo "stopped $s"
    fi
    rm -f "$(pid_file "$s")"
  done
  if [[ "${1:-}" == "--all" ]]; then
    (cd "$ROOT" && docker compose stop postgres redis)
  else
    echo "Postgres and Redis left running (add --all to stop them too)."
  fi
}

cmd_status() {
  local s state
  for s in "${SERVICES[@]}"; do
    if is_running "$s"; then state="running (pid $(cat "$(pid_file "$s")"))"; else state="stopped"; fi
    printf '%-6s %s\n' "$s" "$state"
  done
  if [[ -f "$PORTS_FILE" ]]; then
    load_ports
    echo
    say "Open these"
    echo "  Guest app   http://localhost:$GUEST_PORT      (guests arrive via a table QR: /t/<token>)"
    echo "  Staff app   http://localhost:$STAFF_PORT/login (owner and staff)"
    echo "  Admin app   http://localhost:$ADMIN_PORT"
    echo "  API docs    http://localhost:$API_PORT/docs"
    echo "  Sign-in code in development: $DEV_OTP"
    [[ -f "$RUN/demo.txt" ]] && { echo; cat "$RUN/demo.txt"; }
  fi
}

cmd_logs() {
  local target="${1:-}"
  if [[ -n "$target" ]]; then tail -n 80 -f "$LOGS/$target.log"; else tail -n 20 -f "$LOGS"/*.log; fi
}

case "${1:-up}" in
  up) shift || true; cmd_up "${1:-}" ;;
  down) shift || true; cmd_down "${1:-}" ;;
  status) cmd_status ;;
  logs) shift || true; cmd_logs "${1:-}" ;;
  restart) shift || true; cmd_down; cmd_up "${1:-}" ;;
  *) sed -n '2,12p' "${BASH_SOURCE[0]}"; exit 2 ;;
esac
