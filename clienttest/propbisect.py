#!/usr/bin/env python3
"""Find the static prop model that breaks a view: propbisect.py <map.bsp> <setpos/setang line> [--probe all|none]

Hides a set of static prop models (LeafCount = 0, so the engine never draws them) in a copy of the map,
loads it in the owner's client through the HUD harness at one view, and measures the top of the frame.
Built for Detour Ahead 4 (2026-10-19): facing the bridge the sky went black and no static props drew,
with "vertexlit_and_unlit_generic_ps30 ... Couldn't load combo 520" in the log.
"""
import sys
sys.path = [p for p in sys.path if not p.rstrip("/").endswith("clienttest")]  # clienttest/bisect.py shadows stdlib bisect
import io, os, shutil, struct, subprocess, zipfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import bspinfo

HARNESS = '/home/volence/l4d/hud/ingame-harness'
ADDONS = '/home/volence/l4d1-dt-client/left4dead/addons'   # the private client, never the owner's install
VENV_PY = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.venv', 'bin', 'python')
WORK = '/home/volence/l4d1-cotest/propbisect'
TESTMAP = 'zzbisect'


def layout(d):
    ver, L = bspinfo.lumps(d)
    v, ofs, ln = bspinfo.gamelumps(d, L)['sprp']
    b = d[ofs:ofs + ln]
    n = struct.unpack('<i', b[:4])[0]
    names = [b[4 + 128 * i:4 + 128 * i + 128].split(b'\0')[0].decode() for i in range(n)]
    p = 4 + 128 * n
    nl = struct.unpack('<i', b[p:p + 4])[0]
    p += 4 + 2 * nl
    cnt = struct.unpack('<i', b[p:p + 4])[0]
    return names, ofs + p + 4, cnt


def ent_blocks(d):
    ver, L = bspinfo.lumps(d)
    o, n = L[0][0], L[0][1]
    t = d[o:o + n].decode('latin1')
    import re
    return [m for m in re.finditer(r'\{[^{}]*\}', t)], t


def model_ents(d):
    blocks, t = ent_blocks(d)
    import re
    return [i for i, m in enumerate(blocks) if re.search(r'"model" "', m.group(0)) and '"classname" "worldspawn"' not in m.group(0)]


def drop_ents(d, drop):
    blocks, t = ent_blocks(d)
    keep = ''.join(m.group(0) + '\n' for i, m in enumerate(blocks) if i not in drop)
    from waterfix import replace_lumps
    tmp = os.path.join(WORK, 'drop.bsp')   # not tempfile: clienttest/bisect.py shadows the stdlib bisect it imports
    open(tmp, 'wb').write(d)
    replace_lumps(tmp, {0: keep.encode('latin1') + b'\0'})
    out = open(tmp, 'rb').read(); os.remove(tmp)
    return out


def hidden_copy(src, hide):
    d = bytearray(open(src, 'rb').read())
    names, rec0, cnt = layout(bytes(d))
    for i in range(cnt):
        r = rec0 + 68 * i
        if struct.unpack('<H', d[r + 24:r + 26])[0] in hide:
            d[r + 28:r + 30] = b'\0\0'   # LeafCount 0: in no leaf, never drawn
    return bytes(d)


def sky_level(png):
    out = subprocess.run(['magick', png, '-crop', '600x150+660+0', '-colorspace', 'gray', '-format', '%[fx:mean*255]', 'info:'],
                         capture_output=True, text=True).stdout
    return float(out or 0)


def probe(src, hide, view, tag):
    os.makedirs(WORK, exist_ok=True)
    pk = os.path.join(WORK, 'pkg', 'maps')
    shutil.rmtree(os.path.join(WORK, 'pkg'), ignore_errors=True)
    os.makedirs(pk)
    data = drop_ents(open(src, 'rb').read(), hide) if MODE == 'ents' else hidden_copy(src, hide)
    open(os.path.join(pk, TESTMAP + '.bsp'), 'wb').write(data)
    vpk = os.path.join(ADDONS, 'zz_propbisect.vpk')
    subprocess.run([VENV_PY, '-c', 'import sys, vpk; p = vpk.new(sys.argv[1]); p.version = 1; p.save(sys.argv[2])',
                    os.path.join(WORK, 'pkg'), vpk], check=True, cwd='/tmp')
    steps = os.path.join(WORK, 'probe.steps')
    open(steps, 'w').write(f'map {TESTMAP} coop\ncmd sb_stop 1; god 1; noclip\nsleep 2\ncmd {view}\nsleep 3\nshot view\n')
    out = os.path.join(WORK, 'shots-' + tag)
    shutil.rmtree(out, ignore_errors=True)
    try:
        subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dtclient.py'), steps, out],
                       capture_output=True, timeout=600)
    finally:
        os.remove(vpk)
    png = os.path.join(out, 'view.png')
    level = sky_level(png) if os.path.exists(png) else -1
    print(f'{tag}: hid {len(hide)} models, sky level {level:.1f}', flush=True)
    return level


MODE = 'props'
if __name__ == '__main__':
    src, view = sys.argv[1], sys.argv[2]
    MODE = sys.argv[3] if len(sys.argv) > 3 else 'props'
    if MODE == 'ents':
        idx = model_ents(open(src, 'rb').read())
        blocks, _ = ent_blocks(open(src, 'rb').read())
        names = {i: blocks[i].group(0).replace(chr(10), ' ')[:300] for i in idx}
    else:
        names = dict(enumerate(layout(open(src, 'rb').read())[0]))
    BLACK = 8.0
    base = probe(src, set(), view, 'none')
    allh = probe(src, set(names), view, 'all')
    if not (base < BLACK <= allh):
        sys.exit(f'{MODE} do not explain it (none={base:.1f}, all hidden={allh:.1f})')
    cand = sorted(names)
    step = 0
    while len(cand) > 1:
        half = cand[:len(cand) // 2]
        step += 1
        if probe(src, set(half), view, f's{step}') >= BLACK:
            cand = half
        else:
            cand = cand[len(cand) // 2:]
    print('CULPRIT', cand[0], names[cand[0]])
