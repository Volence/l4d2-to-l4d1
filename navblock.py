#!/usr/bin/env python3
"""Find func_nav_blocker brushes over saferoom (CHECKPOINT) nav areas in converted maps.

    ./navblock.py            # report every map in out/*/pkg/maps

L4D1 rebuilds each saferoom's areas on every round restart (Checkpoint::OnRoundRestart) and skips blocked ones; with
none left, TerrorNavMesh::FindGoalArea fails ("GetGoalArea: Cannot find end area") and the round has no flow at all:
no boss spawns, !cur reads INT_MIN. L4D2's affectsFlow 0 does not exist in L4D1. The map load is safe (entities spawn
before the nav loads, so a blocker cannot block yet), a round restart is not: a blocker that starts enabled blocks
again at spawn, and one blocked by the previous round's entity stays blocked (a new entity's UnblockNav only frees
areas it blocked itself). So a blocker over a saferoom breaks every half 2. Diescraper 2's elevator_nav_block did,
first PUG on it 2026-10-24; Comp Rework already filters Detour Ahead 4's bridgenavblock1-4. compstripper.py filters
the rest.
"""
import glob, os, struct, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bspinfo, nav

CHECKPOINT = 0x800  # TerrorNavArea spawn attribute
Z_SLOP = 20  # a blocker brush usually starts a little above or below the floor it blocks


def checkpoint_blockers(bsp, navp):
    """[(targetname, hammerid, number of saferoom areas under it)] for the map's func_nav_blockers."""
    d = open(bsp, 'rb').read()
    _, L = bspinfo.lumps(d)
    models = bspinfo.lump(d, L, 14)  # dmodel_t: mins, maxs, origin, headnode, firstface, numfaces = 48 bytes
    cps = [a for a in nav.areas(open(navp, 'rb').read()) if a['spawn'] & CHECKPOINT]
    out = []
    for kv, _ in bspinfo.ents(d, L):
        if kv.get('classname') != 'func_nav_blocker' or not kv.get('model', '').startswith('*'):
            continue
        i = int(kv['model'][1:])
        o = [float(x) for x in kv.get('origin', '0 0 0').split()]
        mn = [v + o[k] for k, v in enumerate(struct.unpack_from('<3f', models, i * 48))]
        mx = [v + o[k] for k, v in enumerate(struct.unpack_from('<3f', models, i * 48 + 12))]
        under = [a for a in cps if a['nw'][0] < mx[0] and a['se'][0] > mn[0] and a['nw'][1] < mx[1] and a['se'][1] > mn[1]
                 and min(a['nw'][2], a['se'][2]) < mx[2] + Z_SLOP and max(a['nw'][2], a['se'][2]) > mn[2] - Z_SLOP]
        if under:
            out.append((kv.get('targetname', ''), kv.get('hammerid', ''), len(under)))
    return out


if __name__ == '__main__':
    for bsp in sorted(glob.glob(os.path.join(HERE, 'out', '*', 'pkg', 'maps', '*.bsp'))):
        navp = bsp[:-4] + '.nav'
        if os.path.exists(navp):
            for name, hid, n in checkpoint_blockers(bsp, navp):
                print(f'{os.path.basename(bsp)[:-4]}: {name or "(unnamed)"} hammerid {hid} over {n} saferoom areas')
