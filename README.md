# l4d2to1: convert L4D2 custom campaigns to L4D1

```
./convert.py ~/Downloads/some_campaign.zip [--name short_name]
```

This produces `out/<name>/<name>_l4d1.vpk`, an addon VPK (v1, the only version L4D1 reads), and
`out/<name>/report.txt`. **Read the report first.** Every line marked `!!` is something the converter
could not carry over. The input can be the gamemaps zip, a bare `.vpk`, or a zip holding several VPKs.

Needs the L4D1 client install (to know what players already have, including our `zz_l4d2maps_*`
pack), the L4D2 install (to pull missing assets from) and `/home/volence/l4d1-ds` (to learn which entity
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

## Files

- `convert.py`: the pipeline (extract, analyse, pull assets, convert maps and navs, fix missions, pack)
- `l4d2to1.py`: BSP and entity conversion; runs standalone as `l4d2to1.py in.bsp out.bsp [drop-prefix...]`
- `nav2to1.py`: nav conversion; runs standalone as `nav2to1.py in.nav out.nav`
- `bspinfo.py`, `nav.py`, `vpkread.py`: readers
