#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -eq 0 ]; then
  echo "usage: $0 COMMAND [ARGS...]" >&2
  exit 2
fi

if ! command -v systemd-run >/dev/null 2>&1; then
  echo "systemd-run not found" >&2
  exit 127
fi

# Quality-guard defaults. CIRC_OPS_CAP is only the retained
# debugger tail; CIRC_ASSERT_MAX_OPS is the hard total-emission limit.
: "${CIRC_ASSERT_MAX_OPS:=200000000}"
: "${CIRC_WALL_TIME_LIMIT_SEC:=300}"
export CIRC_ASSERT_MAX_OPS CIRC_WALL_TIME_LIMIT_SEC

unit="codex-8g-$$-$(basename "$1" | tr -c '[:alnum:]' '-')"

run_args=(
  --user
  --unit="$unit"
  --wait
  --same-dir
  --pipe
  -p MemoryMax=8G
  -p MemorySwapMax=0
  -p OOMPolicy=stop
)

# systemd-run does not reliably preserve per-invocation environment overrides
# like DEBUG_ON_FAIL=1 when crossing into the transient user unit. Forward the
# current exported environment explicitly so debugger hooks and focused runtime
# knobs survive the wrapper boundary.
while IFS= read -r -d '' kv; do
  name="${kv%%=*}"
  # systemd-run --setenv only accepts normal environment identifiers.
  # Exported shell functions like BASH_FUNC_foo%% break the wrapper and do not
  # need to cross into the transient unit.
  if [[ ! "$name" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
    continue
  fi
  run_args+=(--setenv="$kv")
done < <(env -0)

cleanup() {
  # Stop the unit unconditionally — systemctl is idempotent and
  # cheap. Send TERM first then KILL after a brief grace period so
  # systemd-run + the unit's main process exit cleanly.
  systemctl --user stop "$unit" >/dev/null 2>&1 || true
  systemctl --user kill --signal=KILL "$unit" >/dev/null 2>&1 || true
  systemctl --user reset-failed "$unit" >/dev/null 2>&1 || true
  if [ -n "${runner_pid:-}" ]; then
    kill -TERM "$runner_pid" >/dev/null 2>&1 || true
    kill -KILL "$runner_pid" >/dev/null 2>&1 || true
  fi
  if [ -n "${watchdog_pid:-}" ]; then
    kill -KILL "$watchdog_pid" >/dev/null 2>&1 || true
  fi
  if [ -n "${time_watchdog_pid:-}" ]; then
    kill -KILL "$time_watchdog_pid" >/dev/null 2>&1 || true
  fi
}

handle_signal() {
  trap - EXIT INT TERM HUP QUIT
  cleanup
  exit 128
}

trap cleanup EXIT
trap handle_signal INT TERM HUP QUIT

# Parent-death watchdog: covers the SIGKILL case where the wrapper
# bash can't run its own trap. Spawned as a session-detached
# subprocess that polls kill -0 on the wrapper PID; when the wrapper
# vanishes, the unit is forced down.
parent_pid=$$
(
  trap '' INT TERM HUP QUIT
  while kill -0 "$parent_pid" 2>/dev/null; do
    sleep 1
  done
  systemctl --user stop "$unit" >/dev/null 2>&1 || true
  systemctl --user kill --signal=KILL "$unit" >/dev/null 2>&1 || true
  systemctl --user reset-failed "$unit" >/dev/null 2>&1 || true
) </dev/null >/dev/null 2>&1 &
watchdog_pid=$!
disown "$watchdog_pid" 2>/dev/null || true

time_watchdog_pid=
# DEBUG_ON_FAIL drops into an interactive REPL that legitimately blocks
# for an indefinite human/agent timescale. Wall-time watchdog would shoot
# the REPL session out from under you, which is never what's wanted.
# Disable it when DEBUG_ON_FAIL is set; the OOM-stop policy and the 8G
# memory cap still protect against runaway resources.
if [ -n "${DEBUG_ON_FAIL:-}" ] && [ "${DEBUG_ON_FAIL}" != "0" ]; then
  CIRC_WALL_TIME_LIMIT_SEC=0
fi
if [ "${CIRC_WALL_TIME_LIMIT_SEC}" != "0" ]; then
  # Poll for parent death in 1-second slices so the watchdog exits
  # within ~1s of the wrapper, instead of leaving an orphaned sleep
  # child that keeps running for the full timeout. A single long
  # `sleep` here doesn't see kill -KILL on the parent subshell
  # because the sleep itself is a separate child that gets reparented
  # to init and runs to completion.
  (
    trap '' INT TERM HUP QUIT
    elapsed=0
    while kill -0 "$parent_pid" 2>/dev/null \
        && [ "$elapsed" -lt "$CIRC_WALL_TIME_LIMIT_SEC" ]; do
      sleep 1
      elapsed=$((elapsed + 1))
    done
    if kill -0 "$parent_pid" 2>/dev/null; then
      echo "CIRC_WALL_TIME_LIMIT_SEC exceeded: ${CIRC_WALL_TIME_LIMIT_SEC}s for unit $unit" >&2
      systemctl --user stop "$unit" >/dev/null 2>&1 || true
      systemctl --user kill --signal=KILL "$unit" >/dev/null 2>&1 || true
      systemctl --user reset-failed "$unit" >/dev/null 2>&1 || true
      if [ -n "${runner_pid:-}" ]; then
        kill -TERM "$runner_pid" >/dev/null 2>&1 || true
      fi
    fi
  ) &
  time_watchdog_pid=$!
  disown "$time_watchdog_pid" 2>/dev/null || true
fi

set +e
# Background systemd-run so the wrapper's `wait` is interruptible by
# signals (foreground systemd-run --wait blocks syscall delivery).
# stdin still flows through `--pipe` to the unit, so DEBUG_ON_FAIL
# REPL keeps working.
#
# `0<&0` explicitly duplicates stdin onto fd 0 before backgrounding.
# Without this, a non-interactive shell (as used by CI/automation)
# auto-redirects backgrounded process stdin to /dev/null, breaking
# the FIFO-driven REPL routine.
systemd-run "${run_args[@]}" "$@" 0<&0 &
runner_pid=$!
wait "$runner_pid"
rc=$?
set -e

status="$(systemctl --user show "$unit" \
  -p Result \
  -p ExecMainCode \
  -p ExecMainStatus \
  -p ActiveState \
  -p SubState 2>/dev/null || true)"

if [ -n "$status" ]; then
  echo "$status" >&2
fi

if printf '%s\n' "$status" | grep -q '^Result=oom-kill$'; then
  echo "OOM detected for unit $unit" >&2
  exit 137
fi

exit "$rc"
