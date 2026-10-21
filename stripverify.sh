#!/usr/bin/env bash
# Load every map of a converted campaign that has a ported Comp Rework cfg, dump the entity lump stripper
# produced, and check it with stripcheck.py.
#
#   ./stripverify.sh <name> [server_dir] [port]     default server: /home/volence/l4d1-striptest, port 27105
#
# Build the server with ./make-strip-rig.sh. It installs out/<name>/<name>_l4d1.vpk for the run (moving aside any
# addon with the same first map, like dictbuild.sh) and the ported cfgs into addons/stripper/Roto-AZMod/maps,
# where the production match config points stripper. Exit 1 if any map fails to load or check.
set -uo pipefail
NAME=$1 SERVER=${2:-/home/volence/l4d1-striptest} PORT=${3:-27105}
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=$HERE/out/$NAME ADDONS=$SERVER/left4dead/addons STRIP=$SERVER/left4dead/addons/stripper
VPK=$OUT/${NAME}_l4d1.vpk LOG=$OUT/stripverify-console.log
[ -d "$SERVER" ] || { echo "no $SERVER: run ./make-strip-rig.sh"; exit 1; }
MAPS=$(cd "$OUT/rotoblin/stripper" && grep -l '^; Ported from' *.cfg 2>/dev/null | sed 's/\.cfg$//')
[ -n "$MAPS" ] || { echo "$NAME: no ported cfgs, nothing to verify"; exit 0; }
PW=$(sed -n 's/^rcon_password "\(.*\)".*/\1/p' "$SERVER/left4dead/cfg/secrets.cfg")
R() { timeout 30 python3 "$HERE/rcon.py" 127.0.0.1 "$PORT" "$PW" "$@" 2>/dev/null; }
ours() { for p in $(pidof srcds_linux); do grep -qa -- "$PORT" "/proc/$p/cmdline" && echo "$p"; done; }
[[ -z "$(ours)" ]] || { echo "a server already runs on port $PORT"; exit 1; }

ASIDE=$ADDONS/_stripverify_aside; mkdir -p "$ASIDE"
first=$(cd "$OUT/pkg/maps" && ls *.bsp | head -1 | sed 's/\.bsp$//')
for v in "$ADDONS"/*.vpk; do
  python3 -c "import sys; sys.path.insert(0,'$HERE'); import vpkread
f,b,es=vpkread.entries(sys.argv[1]); sys.exit(0 if any(e[0].lower()=='maps/$first.bsp' for e in es) else 1)" "$v" \
    && mv "$v" "$ASIDE/"
done
cp "$VPK" "$ADDONS/000_stripverify.vpk"
restore() { for p in $(ours); do kill "$p"; done; sleep 3; rm -f "$ADDONS/000_stripverify.vpk"
            mv "$ASIDE"/*.vpk "$ADDONS/" 2>/dev/null; rmdir "$ASIDE" 2>/dev/null; }
trap restore EXIT
for m in $MAPS; do cp --remove-destination "$OUT/rotoblin/stripper/$m.cfg" "$STRIP/Roto-AZMod/maps/"; done

: > "$LOG"
(cd "$SERVER" && ./srcds_run -console -game left4dead -ip 0.0.0.0 -port "$PORT" -tickrate 100 -maxplayers 31 \
  -norestart -nohltv +sv_lan 1 +exec server +map l4d_vs_airport01_greenhouse >> "$LOG" 2>&1 < /dev/null &)
for _ in $(seq 120); do R status >/dev/null && break; sleep 2; done
sleep 8; R "exec pug_match" >/dev/null; sleep 15
fail=0
for m in $MAPS; do
  R "changelevel $m" >/dev/null
  # the console log is block-buffered, so ask the server which map it is on
  ok=; for _ in $(seq 90); do sleep 2; R status | grep -Eq "^map +: $m( |\$)" && { ok=1; break; }; done
  [ -n "$ok" ] || { echo "$m: did not load"; fail=1; continue; }
  sleep 10
  before=$(ls -t "$STRIP"/dumps/"$m".*.cfg 2>/dev/null | head -1)
  R "stripper_dump" >/dev/null; sleep 3
  dump=$(ls -t "$STRIP"/dumps/"$m".*.cfg 2>/dev/null | head -1)
  [[ -n $dump && $dump != "$before" ]] || { echo "$m: no stripper dump"; fail=1; continue; }
  python3 "$HERE/stripcheck.py" "$OUT/rotoblin/stripper/$m.cfg" "$dump" || fail=1
done
grep -aiE "Host_Error|Segmentation|no free edicts" "$LOG" && fail=1
exit $fail
