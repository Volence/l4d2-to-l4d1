#!/usr/bin/env python3
"""bspedit.py in.bsp out.bsp [drop:N ...] [nodetail] : v20 BSP, empty lumps N, and/or empty dprp/dplt/dplh."""
import struct, sys
src, dst, ops = sys.argv[1], sys.argv[2], sys.argv[3:]
d = open(src, 'rb').read()
L = [list(struct.unpack('<iiii', d[8 + 16 * i:24 + 16 * i])) for i in range(64)]  # ofs, len, ver, cc
data = {i: d[o:o + n] for i, (o, n, v, c) in enumerate(L)}
for op in ops:
    if op.startswith('drop:'):
        data[int(op[5:])] = b''
go = L[35][0]; n = struct.unpack('<i', d[go:go + 4])[0]
heads = [list(struct.unpack('<iHHii', d[go + 4 + 16 * i:go + 20 + 16 * i])) for i in range(n)]
bodies = [d[h[3]:h[3] + h[4]] for h in heads]
if 'nodetail' in ops:
    for k, h in enumerate(heads):
        tag = h[0].to_bytes(4, 'big')
        if tag == b'dprp': bodies[k] = struct.pack('<iii', 0, 0, 0)
        if tag in (b'dplt', b'dplh'): bodies[k] = b''
out = bytearray(1036)
for i in sorted(range(64), key=lambda i: L[i][0]):
    while len(out) % 4: out += b'\0'
    if i == 35:
        base = len(out) + 4 + 16 * n; hdr = struct.pack('<i', n); pos = base
        for h, b in zip(heads, bodies):
            hdr += struct.pack('<iHHii', h[0], h[1], h[2], pos, len(b)); pos += len(b)
        blob = hdr + b''.join(bodies)
    else:
        blob = data[i]
    L[i][0], L[i][1] = (len(out), len(blob)) if blob else (0, 0)
    out += blob
out[0:8] = d[0:8]
for i in range(64): out[8 + 16 * i:24 + 16 * i] = struct.pack('<iiii', *L[i])
out[1032:1036] = d[1032:1036]
open(dst, 'wb').write(out)
