# l4d2to1: convert L4D2 custom campaigns to L4D1

```
./convert.py ~/Downloads/some_campaign.zip --name short_name   # VPK, report, Rotoblin starter files
./flowdump.sh short_name                                        # the game's real flow for every map
./rotoblin.py out/short_name/pkg                                # regenerate Rotoblin files from it
./dictbuild.sh short_name                                       # L4D1 string table dictionaries (REQUIRED)
```

**Never ship a VPK without `dictbuild.sh`.** Every rebuild with `convert.py` puts L4D2's string table
dictionary back into each BSP. Where it misses L4D1's sounds and scenes, the first SourceTV demo of a
match overflows a 96000-byte engine buffer and the dedicated server dies (Carried Off took Dallas down at
match 727, 2026-10-18). `dictbuild.sh` loads each map on the Dallas mirror (`/home/volence/l4d1-cotest`,
an rsync of Dallas with its logaddress pointed at a dead port), runs `stringtabledictionary`, packs the
result with `dictfix.py` and repacks the VPK. The BSP changes, so players need the new VPK.

Then read `out/<name>/report.txt`, edit `out/<name>/rotoblin/`, play every map, and integrate
(see "Rotoblin integration" below).

The first step produces `out/<name>/<name>_l4d1.vpk`, an addon VPK (v1, the only version L4D1 reads), and
`out/<name>/report.txt`. **Read the report first.** Every line marked `!!` is something the converter
could not carry over. The input can be the gamemaps zip, a bare `.vpk`, or a zip holding several VPKs.

Needs the L4D1 client install (to know what players already have, including our `l4d2maps_*`
pack, whatever its `zz_`/`00_` prefix), the L4D2 install (to pull missing assets from) and `/home/volence/l4d1-ds` (to learn which entity
classes L4D1 knows). Paths are at the top of `convert.py`. The first run builds `out/.index.pkl`;
delete it after installing new packs.

First converted: **Crash Course ReRouted** (gamemaps 28094, author MK gave the owner permission),
2026-10-08. All 5 maps boot on a server, and maps 1-4 have been played in the client.

## Will a campaign convert?

The report answers this. The deciding factor is **VScript**: L4D1 has none. If the report lists shipped
`scripts/vscripts` files, `logic_script` entities or script hooks on a finale, that behaviour is lost, and
someone has to rebuild it as a SourceMod plugin or a stock-style `trigger_finale`. CCR had one leftover
call, so it was an easy first case. Everything else below is mechanical.

## What differs between the formats (all verified on real files)

| Piece | L4D2 | L4D1 | Converter |
|---|---|---|---|
| BSP header | v21, lump_t = version, ofs, len, fourCC | v20, lump_t = ofs, len, version, fourCC | rewrite header and relay out the lumps |
| Lump formats | | | all other lump versions are identical, nothing to do |
| Static props (`sprp`) | v9, 72-byte records | v8, 68-byte records | drop the 4 trailing bytes of each record |
| Game lump offsets | absolute file offsets | same | recompute after relayout |
| Entity I/O | fields separated by ESC (0x1b) | separated by commas | replace |
| Nav | v16, sub 14 | v15, sub 13 | same per-area layout, **but** the visible-area set stores area *indices* in L4D2 and area *IDs* in L4D1; remap. Bumping only the version gives ~550k "Invalid area in visible set" lines |
| Models | MDL v49 | L4D1 also ships v49 | copy as-is, except the drop list below |
| Mission file | | same format | lower-case `"Map"` names to match the files |

Lighting: CCR shipped both LDR and HDR lighting. The newer l4d2onl4d pack shows an L4D2 map can ship HDR only,
which renders badly on `mat_hdr_level 0`. Lump 8 (LDR lighting) empty is the tell, and nothing short of a
recompile fixes it.

## Entity conversion (`l4d2to1.py`)

- `weapon_spawn` uses `weapon_selection`; tier1_shotgun -> pump, any_smg -> uzi, tier2_shotgun -> auto,
  any_rifle -> M16, any_sniper_rifle -> hunting rifle, any_pistol -> pistol. "Any" selections pick one
  per spawn, chosen deterministically from the hammerid.
- `weapon_item_spawn` flags, from the L4D2 FGD: 1 ammo, 2 medkit, 3 molotov, 4 pills, 5 pipe, 6 oxygen,
  7 propane, 8 gascan, 11 adrenaline, 12 defib, 13 bile, 16 chainsaw, 17 GL, 18 M60. Adrenaline becomes
  pills and bile becomes a pipe bomb; canisters become `prop_physics`.
- Melee, chainsaw, grenade launcher, M60, upgrade packs and defibs are dropped. The magnum becomes a pistol,
  and `prop_minigun_l4d1` becomes `prop_minigun`.
- Outputs that call scripts or scavenge mode are stripped.
- **Start-room weapons get "Must Exist" (spawnflag 2).** L4D1's director culls weapon spawns without it once
  humans are in. CCR map 4's start room came up empty in the client until this was added. It did NOT
  reproduce on a dedicated server with bots, so test this in the client.

## Model drop list

`--drop-models` (default `models/deadbodies/`) removes static props whose model players lack and whose
path starts with a listed prefix. Copies already in stock L4D1 or our pack are kept.
The L4D2 corpse piles crashed the L4D1 client in `studiorender.dll` (access violation at +0x3CCD2) while
the dedicated server loaded them fine. **A server boot test proves nothing about client rendering.** If a
converted map crashes the client, find the `seh:dispatch_exception` access violation in `~/steam-500.log`,
match the address against the `Loaded L"...dll" at` lines, and add a prefix for whatever L4D2-only models
the map pulled in.

## Testing a conversion

1. Boot every map on an isolated server so you don't disturb the shared local one: `cp -al` a server
   install (hard links, no disk cost), remove `metamod.vdf` and the other `.vdf`s from the copy, comment
   out the metamod line in its `gameinfo.txt` (sed writes a new file, so the original is untouched), drop
   the VPK into its `addons`, then run `srcds_linux ... +mp_gamemode versus +map <map>`. Grep the log for
   `Invalid area`, `missing modelname` and crashes. `/home/volence/l4d1-ccrtest` is one such copy.
2. Play every map in the client: visuals, start-room weapons, the finale and the last saferoom.
   Never overwrite the VPK while the game is running.
3. Then the competitive side: Rotoblin stripper config, boss flow and the pug campaign pool
   (a campaign pools only if it is installed on every enabled server).

## Mission file

Besides lower-casing map names, `convert.py` rewrites L4D2 scoring into L4D1's: `VersusCompletionScore`
becomes a per-map `"VersusModifier"` (400 points = 1.0; stock L4D1 runs 1.0 to 1.75), and boss chances
written as percentages ("75") become fractions (0.75).

## Rotoblin integration

Harry (Rotoblin-AZMod) never edits a map file. Each supported map gets a stripper config
(`addons/stripper/Roto-AZMod/maps/<map>.cfg`: infected ladders, cover props, clips, item and ammo
changes, event fixes) and a block in `data/mapinfo.txt` (`VersusModifier`, `pill_limit`, boss ban
windows, behaviour flags). Some campaigns also get menu entries and the odd hardcoded fix in plugin code.
We override both files from `deploy/overrides/`.

`rotoblin.py` (run by `convert.py`) writes starters for both into `out/<name>/rotoblin/`:

- `mapinfo.txt`: one block per map. **Bosses need no setup:** our `l4d_versus_same_UnprohibitBosses`
  fork forces a tank and a witch on every map, rolled between 10% and 80% true flow (`local_4v4.cfg`)
  and never past 99% minus the boss buffer, whatever the mission says. So a block carries only what the
  defaults get wrong: `VersusModifier` (scoring) from the mission; a tank ban from 5% before to 15%
  after each panic event, elevator and moving platform; and `versus_boss_flow_max` only on short maps,
  where 90 minus the boss buffer (2200 units as a % of the map, our match 363 door-camp rule) is under
  the global 80. The author's L4D2 "no bosses" Director Scripts never apply here (the fork overrides
  them, and L4D1 has no VScript), so they appear commented out as a hint only.
- `stripper/<map>.cfg`: Harry's section layout, a header listing start, end, events, car alarms and
  no-boss stretches with flow %, and an ammo pile on the start-room floor beside the guns when the
  author left none. Verified on CCR: the configs load, and maps 1 and 4 gain exactly that one pile.
- `flow.txt`: the same facts per map in one place.

**Flow numbers must be the game's.** `flowdump.sh` boots the isolated test server, loads each map and runs
the `flowdump` plugin (`flowdump/flowdump.sp`, left4dhooks: every nav area's flow plus the map's max flow)
into `out/<name>/flowdump/`, which `convert.py` keeps across rebuilds. Without a dump the generator falls
back to a nav shortest-walk ESTIMATE and labels every number with it; that estimate came out at 0.4 to
1.0x of the real length on stock maps (ladders, lifts and infected-only shortcuts), so do not ship it.
An empty server gets most maps right (Greenhouse 10362 vs 10362 measured live, Offices 21636 vs 21818)
but not all (Terminal 18534 vs 23851, hospital04 0), so confirm each map once in a live round: the
realflow boss fork logs `[realflow] ... maxflow`.

**To ship a campaign** (none of this is automatic, and live servers change only when the owner says so):
1. Upload the VPK through the site's custom campaign uploader so it lands on every pool server.
2. Paste the edited `mapinfo.txt` blocks into `deploy/overrides/left4dead/addons/sourcemod/data/mapinfo.txt`
   and copy the stripper configs into `deploy/overrides/left4dead/addons/stripper/Roto-AZMod/maps/`.
3. Deploy the overrides with the usual empty-server rules (`deploy/README.md`).

## Test server

`make-test-server.sh` builds `/home/volence/l4d1-ccrtest`: a hard-link copy of the shared local server
(no disk cost) with only left4dhooks and flowdump loaded, so nothing talks to the live PUG site.
Hard links share contents, so it never writes into a linked file. Configs are edited with sed (a new
file), and `logs/` and the flowdump output are directories of its own. (The first run appended to the
shared server's SourceMod error log through a linked `logs/` file; the script now replaces that dir.)
An empty L4D1 server hibernates and stops running timers, so scripts drive it over rcon (`rcon.py`).

## Files

- `dictfix.py` / `dictbuild.sh`: L4D1 string table dictionary per map (see the top of this file)

- `convert.py`: the pipeline (extract, analyse, pull assets, convert maps and navs, fix missions, pack)
- `l4d2to1.py`: BSP and entity conversion; runs standalone as `l4d2to1.py in.bsp out.bsp [drop-prefix...]`
- `nav2to1.py`: nav conversion; runs standalone as `nav2to1.py in.nav out.nav`
- `rotoblin.py`: Rotoblin starter files (mapinfo blocks, stripper configs, flow summary)
- `flowdump.sh`, `flowdump/flowdump.sp`: dump the game's nav flow per map (`.smx` built with the Rotoblin
  spcomp under wine: copy `practice/build/{spcomp.exe,include}` into `flowdump/`, then
  `wine ./spcomp.exe flowdump.sp -o flowdump.smx -iinclude`)
- `make-test-server.sh`, `rcon.py`: the isolated test server and a minimal rcon client
- `bspinfo.py`, `nav.py`, `vpkread.py`: readers
