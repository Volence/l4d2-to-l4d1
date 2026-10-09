#!/bin/bash
# Dump the game's own nav flow for every map of a converted campaign, for rotoblin.py.
#
#   ./flowdump.sh <name>        e.g. ./flowdump.sh ccrerouted   (after ./convert.py ... --name ccrerouted)
#
# Boots the isolated test server (make-test-server.sh) with out/<name>/<name>_l4d1.vpk, loads each map
# over rcon, runs sm_flowdump, and collects the files into out/<name>/flowdump/. Then rerun
# ./rotoblin.py out/<name>/pkg to regenerate the Rotoblin files from real flow.
#
# An empty server reports the right flow on most maps but not all (stock DA-4 reads 18534 against
# 23851 in a live round, hospital04 reads 0). rotoblin.py flags maxflow 0; confirm every map's length
# once in a round with a human (the realflow boss fork logs "[realflow] ... maxflow").
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
NAME=$1
TS=${TEST_SERVER:-/home/volence/l4d1-ccrtest}
PORT=27075
OUT=$HERE/out/$NAME
VPK=$OUT/${NAME}_l4d1.vpk
[ -f "$VPK" ] || { echo "no $VPK; run convert.py first"; exit 1; }
if ss -uln | grep -q ":$PORT "; then echo "something already runs on port $PORT"; exit 1; fi

"$HERE/make-test-server.sh" "$TS"
cp "$VPK" "$TS/left4dead/addons/${NAME}_l4d1.vpk"
MAPS=$(cd "$OUT/pkg/maps" && ls *.bsp | sed 's/\.bsp$//')
FIRST=$(echo "$MAPS" | head -1)
PW=$(grep -h -o 'rcon_password *"[^"]*"' "$TS/left4dead/cfg/secrets.cfg" | tail -1 | sed 's/.*"\(.*\)"/\1/')
LOG=$OUT/flowdump-server.log
DUMP=$TS/left4dead/addons/sourcemod/data/flowdump

cd "$TS"
LD_LIBRARY_PATH=.:bin setsid ./srcds_linux -console -game left4dead -ip 0.0.0.0 -port $PORT -nohltv \
  -tickrate 100 -maxplayers 8 +sv_lan 1 +mp_gamemode versus +map "$FIRST" > "$LOG" 2>&1 < /dev/null &
PID=$!
trap 'kill $PID 2>/dev/null || true' EXIT
for _ in $(seq 1 90); do grep -q "Host_NewGame on map" "$LOG" && break; sleep 1; done
sleep 6

rc() { timeout 10 python3 "$HERE/rcon.py" 127.0.0.1 $PORT "$PW" "$@" >/dev/null 2>&1 || true; }
mkdir -p "$OUT/flowdump"
for m in $MAPS; do
  [ "$m" = "$FIRST" ] || { rc "changelevel $m"; sleep 14; }
  rm -f "$DUMP/$m.txt"
  rc "sm_flowdump"; sleep 1
  if [ -f "$DUMP/$m.txt" ]; then
    cp "$DUMP/$m.txt" "$OUT/flowdump/"; echo "$m: $(head -1 "$DUMP/$m.txt")"
  else
    echo "$m: NO DUMP (did the map load? see $LOG)"
  fi
done
