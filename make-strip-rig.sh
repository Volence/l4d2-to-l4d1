#!/usr/bin/env bash
# Build (or repair) the private server stripverify.sh loads ported cfgs on: /home/volence/l4d1-striptest.
#
#   ./make-strip-rig.sh [dest]
#
# A hard-link copy of /home/volence/l4d1-cotest/server (an rsync of Dallas, logaddress pointed at a dead port),
# so Rotoblin, stripper and the global filters are the production ones. Hard links share contents with cotest:
# anything this server writes must be a fresh file (cp --remove-destination, own logs/ and dumps/).
# The plugins that talk to the site or other servers go to plugins/disabled (SourceMod loads plugins from every
# subfolder EXCEPT one named exactly "disabled").
set -euo pipefail
SRC=/home/volence/l4d1-cotest/server
DEST=${1:-/home/volence/l4d1-striptest}
[ -d "$DEST" ] || cp -al "$SRC" "$DEST"
G=$DEST/left4dead SM=$G/addons/sourcemod
mkdir -p "$SM/plugins/disabled"
for p in l4d_booking l4d_lilac_report l4d_spray_report l4d_tvwatch lilac pug-match pug-sidegame l4d_consistency; do
  [ -f "$SM/plugins/$p.smx" ] && mv "$SM/plugins/$p.smx" "$SM/plugins/disabled/"
done
for d in "$SM/logs" "$G/logs" "$G/addons/stripper/dumps"; do
  if [ -n "$(find "$d" -type f -links +1 2>/dev/null | head -1)" ]; then rm -rf "$d"; mkdir -p "$d"; fi
done
echo "strip rig ready: $DEST (port 27105 via stripverify.sh)"
