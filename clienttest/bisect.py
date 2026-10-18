#!/usr/bin/env python3
"""Find what makes a converted map crash the L4D1 client.

    ./bisect.py <campaign> <map>

Builds variants of out/<campaign>/pkg with maps/<map>.bsp changed, packs each, and runs try.sh on it
(launch muted, load the map, ALIVE or CRASH). Order: no static props; bare world (entities cut to the
essentials, no pak, no detail props); then halves of the entity list or of the world material list
(texswap.py, everything swapped to stock brick) until one culprit is left.
"""
import os, re, shutil, struct, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import l4d2to1, waterfix, pickle
import convert as convert_py
L2 = pickle.load(open(f'{os.path.dirname(HERE)}/out/.index.pkl', 'rb'))[1]

camp, mapname = sys.argv[1], sys.argv[2]
PKG = f'{HERE}/../out/{camp}/pkg'
SRC = f'{HERE}/../out/{camp}/src/maps/{mapname}.bsp'
CONV = f'{PKG}/maps/{mapname}.bsp'
ESSENTIAL = {'worldspawn', 'info_player_start', 'info_survivor_position', 'info_landmark'}
n_run = 0


def run(label, make_bsp):
    """make_bsp(path) writes the variant BSP; returns True if the client survived."""
    global n_run
    n_run += 1
    name = f'bs{n_run}'
    v = f'{HERE}/v/{name}'
    shutil.rmtree(v, ignore_errors=True)
    shutil.copytree(PKG, v, copy_function=os.link)
    os.remove(f'{v}/maps/{mapname}.bsp')
    make_bsp(f'{v}/maps/{mapname}.bsp')
    subprocess.run([f'{HERE}/mk.sh', name], check=True, stderr=subprocess.DEVNULL)
    out = subprocess.run([f'{HERE}/try.sh', name, mapname, f'{HERE}/v/hftest_{name}.vpk'],
                         capture_output=True, text=True).stdout
    shutil.rmtree(v, ignore_errors=True)
    os.remove(f'{HERE}/v/hftest_{name}.vpk')
    alive = 'ALIVE' in out.splitlines()[0] if out else False
    print(f'{label}: {"ALIVE" if alive else "CRASH"}', flush=True)
    return alive


def convert(dst, keep_entity=None, drop_props=False):
    orig = l4d2to1.convert_entity
    if keep_entity:
        l4d2to1.convert_entity = lambda pairs, log: orig(pairs, log) if keep_entity(pairs) else None
    try:
        l4d2to1.convert(SRC, dst, ('models/',) if drop_props else ('models/deadbodies/',))
    finally:
        l4d2to1.convert_entity = orig
    # the shipped map also went through waterfix (convert.py); without it every variant regains the
    # flow-map water crash and the bisect chases it instead (Open Road x1m2, 2026-10-17)
    waterfix.fix([dst], read_vmt, lambda name, text: None, lambda t: True, lambda s: None)


def read_vmt(name):
    f = f'{PKG}/materials/{name}.vmt'
    if os.path.exists(f):
        return open(f, encoding='latin1').read()
    e = L2.get(f'materials/{name}.vmt')
    return convert_py.vpk_read(e).decode('latin1') if e else None


def bare(dst, extra_keep=lambda i: False):
    idx = {'i': -1}

    def keep(pairs):
        idx['i'] += 1
        return dict(pairs).get('classname') in ESSENTIAL or extra_keep(idx['i'])
    tmp = dst + '.tmp'
    convert(tmp, keep, drop_props=True)
    subprocess.run([sys.executable, f'{HERE}/bspedit.py', tmp, dst, 'drop:40', 'drop:41', 'nodetail'], check=True)
    os.remove(tmp)


if run('as converted', lambda p: shutil.copy(CONV, p)):
    sys.exit('the converted map does not crash here')
if run('no static props', lambda p: convert(p, drop_props=True)):
    print('=> a static prop model')
    sys.exit()
if not run('bare world', bare):
    # world: bisect materials on the bare map
    tmp = f'{HERE}/v/bare.bsp'
    bare(tmp)
    if not run('bare world, all materials -> brick',
               lambda p: subprocess.run([sys.executable, f'{HERE}/texswap.py', tmp, p, 'brick/brickwall001a', '0', '99999'],
                                        check=True, stdout=subprocess.DEVNULL)):
        sys.exit('=> world geometry/lighting, not a material')
    d = open(tmp, 'rb').read()
    L = lambda i: struct.unpack('<iiii', d[8 + 16 * i:24 + 16 * i])
    s = d[L(43)[0]:L(43)[0] + L(43)[1]]
    offs = struct.unpack(f'<{L(44)[1] // 4}i', d[L(44)[0]:L(44)[0] + L(44)[1]])
    nm = lambda x: s[x:s.index(b'\0', x)].lower()
    uniq = sorted({nm(x) for x in offs if not nm(x).startswith(b'tools/')})
    lo, hi = 0, len(uniq)
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if run(f'materials [{lo},{mid}) swapped',
               lambda p: subprocess.run([sys.executable, f'{HERE}/texswap.py', tmp, p, 'brick/brickwall001a', str(lo), str(mid)],
                                        check=True, stdout=subprocess.DEVNULL)):
            hi = mid
        else:
            lo = mid
    print('=> world material', uniq[lo].decode())
    sys.exit()
# bare world survives: an entity (props are already ruled out). Bisect by adding entity ranges back.
d = open(SRC, 'rb').read()
_, eo, el, _ = struct.unpack('<iiii', d[8:24])  # v21 lump_t: version, ofs, len, fourCC
src_ents = l4d2to1.parse_ents(d[eo:eo + el].decode('latin1'))
lo, hi = 0, len(src_ents)
while hi - lo > 1:  # invariant: entities [lo,hi) hold the culprit
    mid = (lo + hi) // 2
    if run(f'entities [{lo},{mid}) kept', lambda p: bare(p, lambda i: lo <= i < mid)):
        lo = mid
    else:
        hi = mid
print('=> entity', lo, dict(src_ents[lo]))
