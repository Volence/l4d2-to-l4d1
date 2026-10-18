#!/usr/bin/env bash
# Crash probe: ./try.sh <label> <map> <vpk>...  Installs the VPKs into the client addons (removing them after),
# launches L4D1 muted/windowed with netcon, loads <map> in coop, and reports CRASH or ALIVE after 45 s in game.
# Owner's standing OK to launch the client (memory feedback-ingame-harness-ok); never runs under a live game.
set -uo pipefail
source /home/volence/l4d/hud/ingame-harness/lib.sh
HERE=$(cd "$(dirname "$0")" && pwd)
LABEL=$1 MAP=$2; shift 2
[[ -z "$(game_pids)" ]] || { echo "game running, not touching it"; exit 1; }
exec 9> "$LOCKFILE"; flock -n 9 || { echo "harness lock held"; exit 1; }
mkdir -p "$HERE/runs"; OUT="$HERE/runs/$(date +%H%M%S)-$LABEL"; mkdir -p "$OUT"
INST=()
for v in "$@"; do b=$(basename "$v"); [[ -e "$ADDONS/$b" ]] && { echo "$b already in addons, refusing"; exit 1; }; cp "$v" "$ADDONS/$b"; INST+=("$ADDONS/$b"); done
cleanup() { [[ -n "$(game_pids)" ]] && { python3 "$HARNESS_DIR/netcon.py" $PORT $PW --read 0.5 quit >/dev/null 2>&1; sleep 5; kill $(game_pids) 2>/dev/null; sleep 2; }
            for f in "${INST[@]}"; do rm -f "$f"; done; cp "$L4D/console.log" "$OUT/" 2>/dev/null; }
trap cleanup EXIT
PORT=$(( 27100 + RANDOM % 800 )); PW="hx$RANDOM$RANDOM"
: > "$L4D/console.log"
steam -applaunch 500 -novid -nosound -windowed -noborder -w 1280 -h 720 -condebug -netconport $PORT -netconpassword $PW >/dev/null 2>&1 &
for _ in $(seq 1 180); do sleep 1; python3 "$HARNESS_DIR/netcon.py" $PORT $PW --probe && break; done
for _ in $(seq 1 30); do python3 "$HARNESS_DIR/netcon.py" $PORT $PW --read 1 "echo hx_ready" 2>/dev/null | grep -q hx_ready && break; sleep 1; done
python3 "$HARNESS_DIR/netcon.py" $PORT $PW --read 0.5 "sv_cheats 1; ${PRE:-}; map $MAP coop" >/dev/null 2>&1
for _ in $(seq 1 120); do sleep 1; [[ -z "$(game_pids)" ]] && break; grep -q "Got pure server\|Map: $MAP" "$L4D/console.log" && break; done
for _ in $(seq 1 45); do sleep 1; [[ -z "$(game_pids)" ]] && break; done
if [[ -z "$(game_pids)" ]]; then echo "$LABEL: CRASH"; else echo "$LABEL: ALIVE"; fi
tail -3 "$L4D/console.log"
