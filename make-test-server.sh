#!/bin/bash
# Build (or repair) the isolated L4D1 test server used by flowdump.sh and for boot tests.
#
#   ./make-test-server.sh [dest]        default dest: /home/volence/l4d1-ccrtest
#
# It is a hard-link copy of the shared local server (/home/volence/l4d1-ds/server), so it costs no
# disk. Hard links share file CONTENTS with the original, so anything a test server writes to must
# be a fresh file here: config edits use sed -i (writes a new file), and logs/ and data/flowdump/
# are real directories of their own. Never open a linked file for writing in place.
# Plugins: only left4dhooks and flowdump load, so nothing talks to the live PUG site.
set -euo pipefail
SRC=/home/volence/l4d1-ds/server
DEST=${1:-/home/volence/l4d1-ccrtest}
HERE=$(cd "$(dirname "$0")" && pwd)

[ -d "$DEST" ] || cp -al "$SRC" "$DEST"
G=$DEST/left4dead
# metamod on (it is off after a no-plugin boot test), other VSP plugins off
[ -e "$G/addons/metamod.vdf" ] || ln "$SRC/left4dead/addons/metamod.vdf" "$G/addons/metamod.vdf"
rm -f "$G/addons/sourcetvsupport_vsp_l4d.vdf" "$G/addons/tickrate_enabler_l4d1.vdf"
sed -i 's|^\(\s*\)//\(Game\s*left4dead/addons/metamod\)|\1\2|' "$G/gameinfo.txt"

SM=$G/addons/sourcemod
[ -d "$SM/plugins_full" ] || mv "$SM/plugins" "$SM/plugins_full"
mkdir -p "$SM/plugins"
find "$SM/plugins" -maxdepth 1 -type f -delete
ln -f "$SM/plugins_full/left4dhooks.smx" "$SM/plugins/"
cp "$HERE/flowdump/flowdump.smx" "$SM/plugins/"
# own logs dir (the copied one is hard links into the shared server's logs)
if [ -n "$(find "$SM/logs" -type f -links +1 2>/dev/null | head -1)" ]; then
  rm -rf "$SM/logs"; mkdir -p "$SM/logs"
fi

# the L4D2 pack VPKs, so converted maps find their L4D2 props
for f in "/home/volence/.local/share/Steam/steamapps/common/left 4 dead/left4dead/addons/"*l4d2maps_*.vpk; do
  [ -e "$G/addons/$(basename "$f")" ] || ln "$f" "$G/addons/" 2>/dev/null || cp "$f" "$G/addons/"
done
echo "test server ready: $DEST (port 27075 via flowdump.sh)"
