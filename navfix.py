#!/usr/bin/env python3
"""Apply SirPlease L4D2-Competitive-Rework nav fixes to a converted (L4D1 v15) nav mesh.

    navfix.py <nav> --nut <navfixes.nut> [--cfg <comp stripper cfg>] [-o out.nav]

Comp Rework fixes the nav at map load with VScript (scripts/vscripts/nav_fixes/<map>_navfixes.nut), which L4D1
does not have, and with point_nav_attribute_region entities in the stripper cfg, which L4D1 does not have either.
Both only change data the nav file itself holds, so this writes the change into the file:

- <a>.ConnectTo(<b>, -1): add a one-way connection a -> b in the direction CNavArea::ComputeDirection gives for
  b's centre (the engine's own choice when no direction is passed); skipped when a already connects to b.
- <a>.Disconnect(<b>): remove b from all four of a's connection lists.
  Only the fix functions the .nut actually calls at the bottom are applied (cwm1_intro defines a fix2 it never calls).
- point_nav_attribute_region with remove_attributes 1: clear its spawnflags bits from the TERROR spawn attributes
  of every area whose centre is inside origin+mins..origin+maxs (spawnflags 4096 = OBSCURED). Adding is the same
  with the bits set. Its crouch/stairs/precise/mob_only/tank_only Source-attribute keys are honoured when "1".

Returns a list of human-readable changes; the file is rewritten with each area's connection block spliced.
"""
import argparse, re, struct, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nav import R, header

NORTH, EAST, SOUTH, WEST = range(4)


def parse_areas(d):
    """Areas with byte spans: [start, conn_start, conn_end, spawn_off, end) per area, plus id/extents/conns."""
    r = R(d); ver, sub, n = header(r)
    assert (ver, sub) == (15, 13), f'expected an L4D1 v15/13 nav, got {ver}/{sub}'
    out = []
    for _ in range(n):
        a = {'start': r.p}
        a['id'], a['flags'] = r.u('II')
        a['flags_off'] = r.p - 4
        a['nw'], a['se'] = r.u('fff'), r.u('fff')
        r.p += 8
        a['conn_start'] = r.p
        a['conns'] = []
        for _ in range(4):
            c = r.u('I'); a['conns'].append(list(struct.unpack_from('<%dI' % c, d, r.p))); r.p += 4 * c
        a['conn_end'] = r.p
        hs = r.u('B'); r.p += hs * (4 + 12 + 1)
        ec = r.u('I')
        for _ in range(ec):
            r.p += 4 + 1 + 4 + 1; sc = r.u('B'); r.p += sc * 5
        r.u('H')
        for _ in range(2):
            c = r.u('I'); r.p += 4 * c
        r.p += 8 + 16
        a['spawn_off'] = r.p
        a['spawn'] = r.u('I'); r.u('H')
        c = r.u('I'); r.p += 5 * c
        r.u('I')
        a['end'] = r.p
        a['center'] = tuple((x + y) / 2 for x, y in zip(a['nw'], a['se']))
        out.append(a)
    return out


def compute_direction(a, p):
    """CNavArea::ComputeDirection: which side of area a the point p lies on."""
    (lx, ly, _), (hx, hy, _) = a['nw'], a['se']
    if lx <= p[0] <= hx:
        if p[1] < ly: return NORTH
        if p[1] > hy: return SOUTH
    elif ly <= p[1] <= hy:
        if p[0] < lx: return WEST
        if p[0] > hx: return EAST
    cx, cy = a['center'][0], a['center'][1]
    dx, dy = p[0] - cx, p[1] - cy
    if abs(dx) > abs(dy):
        return EAST if dx > 0 else WEST
    return SOUTH if dy > 0 else NORTH


def nut_ops(text):
    """[('connect'|'disconnect', from id, to id)] for the fix functions the script calls."""
    called = set(re.findall(r'^\s*(\w+)\(\)\s*$', text, re.M))
    ops = []
    for name, body in re.findall(r'function (\w+)\(\)\s*\{(.*?)\n\}', text, re.S):
        if name not in called:
            continue
        ids = dict(re.findall(r'local (\w+) = NavMesh\.GetNavAreaByID\((\d+)\)', body))
        for line in body.split('\n'):
            line = line.split('//')[0]
            m = re.search(r'(\w+)\.ConnectTo\((\w+)\s*,\s*(-?\d+)\)', line)
            if m:
                assert m.group(3) == '-1', 'only ConnectTo(area, -1) is handled'
                ops.append(('connect', int(ids[m.group(1)]), int(ids[m.group(2)]), name))
            m = re.search(r'(\w+)\.Disconnect\((\w+)\)', line)
            if m:
                ops.append(('disconnect', int(ids[m.group(1)]), int(ids[m.group(2)]), name))
    return ops


def cfg_regions(text):
    """point_nav_attribute_region blocks from a stripper cfg, commented out or not."""
    res = []
    for blk in re.findall(r'\{[^{}]*point_nav_attribute_region[^{}]*\}', text.replace('\n;', '\n')):
        kv = dict(re.findall(r'"([^"]+)"\s+"([^"]*)"', blk))
        if kv.get('classname') == 'point_nav_attribute_region':
            res.append(kv)
    return res


def apply(nav_bytes, ops=(), regions=()):
    d = bytes(nav_bytes)
    areas = parse_areas(d)
    by_id = {a['id']: a for a in areas}
    log, conns_changed = [], set()
    for op, f, t, fn in ops:
        a, b = by_id[f], by_id[t]
        if op == 'connect':
            if any(t in c for c in a['conns']):
                log.append(f'{fn}: {f} -> {t} already connected'); continue
            dr = compute_direction(a, b['center'])
            a['conns'][dr].append(t); conns_changed.add(f)
            log.append(f'{fn}: connect {f} -> {t} ({"NESW"[dr]})')
        else:
            if any(t in c for c in a['conns']):
                a['conns'] = [[x for x in c if x != t] for c in a['conns']]; conns_changed.add(f)
                log.append(f'{fn}: disconnect {f} -/-> {t}')
            else:
                log.append(f'{fn}: {f} -/-> {t} was not connected')
    spawn_new, flags_new = {}, {}
    for kv in regions:
        o = [float(x) for x in kv['origin'].split()]
        lo = [o[i] + float(v) for i, v in enumerate(kv['mins'].split())]
        hi = [o[i] + float(v) for i, v in enumerate(kv['maxs'].split())]
        bits = int(kv.get('spawnflags', '0'))
        sbits = 0
        for k, b in (('crouch', 0x1), ('precise', 0x4), ('stairs', 0x1000)):
            if kv.get(k) == '1': sbits |= b
        remove = kv.get('remove_attributes') == '1'
        hit = [a for a in areas if all(lo[i] <= a['center'][i] <= hi[i] for i in range(3))]
        n = 0
        for a in hit:
            s = spawn_new.get(a['id'], a['spawn']); fl = flags_new.get(a['id'], a['flags'])
            s2 = (s & ~bits) if remove else (s | bits); f2 = (fl & ~sbits) if remove else (fl | sbits)
            if s2 != s or f2 != fl:
                spawn_new[a['id']] = s2; flags_new[a['id']] = f2; n += 1
        log.append(f'{kv.get("targetname", "region")}: {"clear" if remove else "set"} spawn bits {bits:#x}'
                   + (f' source bits {sbits:#x}' if sbits else '') + f' on {n} of {len(hit)} areas in the box')
    out, last = bytearray(), 0
    for a in areas:
        if a['id'] in conns_changed:
            out += d[last:a['conn_start']]
            for c in a['conns']:
                out += struct.pack('<I', len(c)) + struct.pack('<%dI' % len(c), *c)
            last = a['conn_end']
    out += d[last:]
    out = bytes(out)
    if spawn_new or flags_new:  # fixed-size fields: patch in place on the re-parsed layout
        b = bytearray(out)
        for a in parse_areas(out):
            if a['id'] in spawn_new: struct.pack_into('<I', b, a['spawn_off'], spawn_new[a['id']])
            if a['id'] in flags_new: struct.pack_into('<I', b, a['flags_off'], flags_new[a['id']])
        out = bytes(b)
    return out, log


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('nav'); ap.add_argument('--nut'); ap.add_argument('--cfg'); ap.add_argument('-o')
    a = ap.parse_args()
    ops = nut_ops(open(a.nut).read()) if a.nut else []
    regions = cfg_regions(open(a.cfg, encoding='latin1').read()) if a.cfg else []
    out, log = apply(open(a.nav, 'rb').read(), ops, regions)
    open(a.o or a.nav, 'wb').write(out)
    print('\n'.join(log))
