"""Minimal reader for L4D/L4D2 nav meshes (v15 sub 13 and v16 sub 14 share the per-area layout)."""
import struct


class R:
    def __init__(s, d, p=0): s.d = d; s.p = p

    def u(s, fmt):
        v = struct.unpack_from('<' + fmt, s.d, s.p); s.p += struct.calcsize('<' + fmt)
        return v if len(v) > 1 else v[0]


def header(r):
    magic, ver, sub, bsp = r.u('IIII'); r.u('B')  # isAnalyzed
    pc = r.u('H')
    for _ in range(pc):
        n = r.u('H'); r.p += n
    r.u('B')  # hasUnnamedAreas
    e = r.d.index(b'\0', r.p); r.p = e + 1  # L4D nav theme name, e.g. "default"
    r.u('B'); r.u('B')
    n = r.u('I'); return ver, sub, n


def area_base(r, ver, out=None):
    """Read the Source part of an area. With out={}, also collect corners and connections."""
    aid, flags = r.u('II')
    nw, se = r.u('fff'), r.u('fff')
    r.p += 8
    conns = []
    for _ in range(4):
        c = r.u('I'); conns += struct.unpack_from('<%dI' % c, r.d, r.p); r.p += 4 * c
    hs = r.u('B'); r.p += hs * (4 + 12 + 1)
    ec = r.u('I')
    for _ in range(ec):
        r.p += 4 + 1 + 4 + 1; sc = r.u('B'); r.p += sc * 5
    r.u('H')
    for _ in range(2):
        c = r.u('I'); r.p += 4 * c
    r.p += 8 + 16
    if ver >= 16:
        c = r.u('I'); r.p += c * 5
        r.u('I')
    if out is not None:
        out.update(id=aid, flags=flags, nw=nw, se=se, conns=conns)
    return aid


def areas(data):
    """All areas of a nav file: list of dicts with id, flags, spawn, nw, se, conns, center."""
    return mesh(data)[0]


def mesh(data):
    """(areas, ladders). A ladder is (bottom area id, [top area ids], length)."""
    r = R(data); _, _, n = header(r); res = []
    for _ in range(n):
        a = {}
        area_base(r, 15, a)
        a['spawn'] = r.u('I'); r.u('H')
        c = r.u('I'); r.p += 5 * c
        r.u('I')
        a['center'] = tuple((x + y) / 2 for x, y in zip(a['nw'], a['se']))
        res.append(a)
    lads = []
    for _ in range(r.u('I')):
        _id, _w = r.u('If'); r.p += 24
        length, _dir = r.u('fI')
        tops = r.u('IIII'); bottom = r.u('I')
        lads.append((bottom, [t for t in tops if t], length))
    return res, lads
