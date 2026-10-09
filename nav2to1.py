#!/usr/bin/env python3
"""Downconvert an L4D2 nav (v16 sub 14) to L4D1 (v15 sub 13).

The per-area layout is identical; the one semantic change is the potentially-visible set:
L4D2 stores each entry as an index into the file's area order, L4D1 stores the area ID.
"""
import struct, sys
sys.path.insert(0, __import__('os').path.dirname(__file__))
from nav import R, header, area_base


def convert(src, dst):
    d = bytearray(open(src, 'rb').read())
    assert struct.unpack_from('<II', d, 4) == (16, 14), 'not an L4D2 v16/14 nav'
    r = R(bytes(d))
    _, _, n = header(r)
    ids, vis_at = [], []
    for _ in range(n):
        st = r.p
        area_base(r, 15)
        ids.append(struct.unpack_from('<I', d, st)[0])
        r.p += 6  # L4D spawn attributes (u32) + u16
        c = r.u('I')
        vis_at.append((r.p, c))
        r.p += 5 * c
        r.u('I')  # inherit-visibility-from, already an area ID
    lc = r.u('I')
    r.p += lc * 60
    assert len(d) - r.p == 4, f'unexpected trailing bytes: {len(d) - r.p}'
    for p, c in vis_at:
        for j in range(c):
            idx = struct.unpack_from('<I', d, p + 5 * j)[0]
            struct.pack_into('<I', d, p + 5 * j, ids[idx])
    struct.pack_into('<II', d, 4, 15, 13)
    open(dst, 'wb').write(d)
    return n, sum(c for _, c in vis_at)


if __name__ == '__main__':
    n, v = convert(sys.argv[1], sys.argv[2])
    print(f'  {n} areas, {v} visibility entries remapped')
