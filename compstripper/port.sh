#!/usr/bin/env bash
# Port SirPlease L4D2-Competitive-Rework zonemod stripper cfgs onto our converted campaigns.
#   compstripper/port.sh <L4D2-Competitive-Rework checkout> <work dir>
# Writes <work dir>/port/*.cfg (raw ports + report.txt) and <work dir>/final/*.cfg (with our flow headers,
# start ammo, and rotated blockers split by deploy/tools/blocker-angles), then copies final/ here.
set -euo pipefail
cd "$(dirname "$0")/.."
CR=$1; W=$2; S=$CR/cfg/stripper/zonemod/maps; C=/home/volence/l4d1-cotest/server
mkdir -p "$W/port" "$W/final" "$W/orsrc"
VP=("$C/left4dead/pak01_dir.vpk" "$C/left4dead_dlc3/pak01_dir.vpk" "$C"/left4dead/addons/zz_l4d2maps_*.vpk)
for pair in detourahead:cdta carriedoff:cwm hauntedforest:hf0 openroad:x1m diescraper:l4d2_diescraper; do
  camp=${pair%%:*}; pre=${pair##*:}
  for cfg in "$S"/$pre*.cfg; do
    m=$(basename "$cfg" .cfg); [[ $m == *_34 || $m == *_35 ]] && continue
    src=out/$camp/src/maps/$m.bsp
    [ -f "$src" ] || src=$W/orsrc/maps/$m.bsp   # Open Road keeps no src/: extract maps/ from in/openroad.vpk there
    python3 stripper2to1.py "$cfg" "$src" "out/$camp/pkg/maps/$m.bsp" "$W/port/$m.cfg" "${VP[@]}" "out/$camp/pkg"
  done
done | tee "$W/port/report.txt"
python3 compstripper/assemble.py "$W"
python3 /home/volence/l4d/deploy/tools/blocker-angles/blocker_angles.py --cap 96 --write "$W"/final/*.cfg | tail -1
cp "$W"/final/*.cfg compstripper/
