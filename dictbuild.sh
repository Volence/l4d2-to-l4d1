#!/usr/bin/env bash
# Give every map of a converted campaign an L4D1 string table dictionary, then repack its VPK.
#
#   ./dictbuild.sh <name> [server_dir] [port]     default server: /home/volence/l4d1-cotest/server, port 27085
#
# Why: a converted BSP keeps the dictionary L4D2 built. When it misses L4D1's sounds and scenes, starting
# a SourceTV demo overflows the 96000-byte signon buffer and the dedicated server dies (Host_Error
# "Overflow error writing string table baseline"; Carried Off killed Dallas at match 727, 2026-10-18).
# See dictfix.py. The server should be a copy of a production box (same plugins precache the same
# strings); /home/volence/l4d1-cotest is an rsync of Dallas with its logaddress pointed at a dead port.
# It installs out/<name>/<name>_l4d1.vpk into that server's addons for the run, moving aside any addon
# that carries the same maps, and puts everything back afterwards.
set -uo pipefail
NAME=$1 SERVER=${2:-/home/volence/l4d1-cotest/server} PORT=${3:-27085}
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=$HERE/out/$NAME PKG=$OUT/pkg ADDONS=$SERVER/left4dead/addons
VPK=$OUT/${NAME}_l4d1.vpk LOG=$OUT/dictbuild-console.log
MAPS=$(cd "$PKG/maps" && ls *.bsp | sed 's/\.bsp$//')
PW=$(sed -n 's/^rcon_password "\(.*\)".*/\1/p' "$SERVER/left4dead/cfg/secrets.cfg")
R() { timeout 30 python3 "$HERE/rcon.py" 127.0.0.1 "$PORT" "$PW" "$@" 2>/dev/null; }
ours() { for p in $(pidof srcds_linux); do grep -qa -- "$PORT" "/proc/$p/cmdline" && echo "$p"; done; }
[[ -z "$(ours)" ]] || { echo "a server already runs on port $PORT"; exit 1; }

# install the campaign, moving aside addons that carry the same first map
ASIDE=$ADDONS/_dictbuild_aside; mkdir -p "$ASIDE"
first=$(echo "$MAPS" | head -1)
for v in "$ADDONS"/*.vpk; do
  python3 -c "import sys; sys.path.insert(0,'$HERE'); import vpkread
f,b,es=vpkread.entries(sys.argv[1]); sys.exit(0 if any(e[0].lower()=='maps/$first.bsp' for e in es) else 1)" "$v" \
    && mv "$v" "$ASIDE/"
done
cp "$VPK" "$ADDONS/000_dictbuild.vpk"
restore() { for p in $(ours); do kill "$p"; done; sleep 3; rm -f "$ADDONS/000_dictbuild.vpk"
            mv "$ASIDE"/*.vpk "$ADDONS/" 2>/dev/null; rmdir "$ASIDE" 2>/dev/null; }
trap restore EXIT

: > "$LOG"
# One fresh server per map, killed with SIGKILL after the dictionary is written: three runs that changed level
# right after `stringtabledictionary` crashed in vphysics teardown (CPhysicsEnvironment::NotifyConstraintDisabled
# from CPhysicsHook::LevelShutdownPostEntity), so no level is ever shut down after it.
for m in $MAPS; do
  rm -f "$SERVER"/left4dead*/reslists/"$m".dict
  (cd "$SERVER" && ./srcds_run -console -game left4dead -ip 0.0.0.0 -port "$PORT" -tickrate 100 -maxplayers 31 \
    -norestart +log on +sv_lan 1 +exec server +map l4d_vs_airport01_greenhouse >> "$LOG" 2>&1 < /dev/null &)
  for _ in $(seq 120); do R status >/dev/null && break; sleep 2; done
  sleep 8; R "exec pug_match" >/dev/null; sleep 15
  R "changelevel $m" >/dev/null
  for _ in $(seq 90); do grep -aq "Started map \"$m\"" "$LOG" && break; sleep 2; done
  sleep 10
  R "stringtabledictionary" >/dev/null; sleep 3
  for p in $(ours); do kill -KILL "$p"; done; sleep 2
  dict=$(ls "$SERVER"/left4dead*/reslists/"$m".dict 2>/dev/null | head -1)
  [[ -n $dict ]] || { echo "$m: no dictionary written"; mkdir -p ~/l4d/crashes/cotest
    cp "$ADDONS"/sourcemod/data/dumps/*.dmp* ~/l4d/crashes/cotest/ 2>/dev/null; exit 1; }
  python3 "$HERE/dictfix.py" "$PKG/maps/$m.bsp" "$dict" && echo "$m: dictionary $(stat -c %s "$dict") bytes packed"
done
"$HERE/.venv/bin/python" -c 'import sys, vpk; p = vpk.new(sys.argv[1]); p.version = 1; p.save(sys.argv[2])' "$PKG" "$VPK" \
  && echo "wrote $VPK"
