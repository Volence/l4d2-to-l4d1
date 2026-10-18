#!/usr/bin/env python3
"""texswap.py in.bsp out.bsp REPL lo hi : texdata names with index in [lo,hi) (sorted unique order) -> REPL."""
import struct, sys
src, dst, repl, lo, hi = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), int(sys.argv[5])
d = bytearray(open(src, 'rb').read())
L = lambda i: struct.unpack('<iiii', d[8 + 16 * i:24 + 16 * i])
o43, n43 = L(43)[:2]; o44, n44 = L(44)[:2]
s = bytes(d[o43:o43 + n43]); offs = list(struct.unpack(f'<{n44 // 4}i', d[o44:o44 + n44]))
name = lambda x: s[x:s.index(b'\0', x)]
uniq = sorted({name(x).lower() for x in offs if not name(x).lower().startswith(b'tools/')})
target = set(uniq[lo:hi])
new = bytearray(); newoffs = []
for x in offs:
    nm = name(x)
    if nm.lower() in target: nm = repl.encode()
    newoffs.append(len(new)); new += nm + b'\0'
# string data grows: append both lumps at the end of the file and repoint
out = bytearray(d)
while len(out) % 4: out += b'\0'
p43 = len(out); out += new
while len(out) % 4: out += b'\0'
p44 = len(out); out += struct.pack(f'<{len(newoffs)}i', *newoffs)
v43, v44 = L(43)[2:], L(44)[2:]
out[8 + 16 * 43:24 + 16 * 43] = struct.pack('<iiii', p43, len(new), *v43)
out[8 + 16 * 44:24 + 16 * 44] = struct.pack('<iiii', p44, 4 * len(newoffs), *v44)
open(dst, 'wb').write(out)
print(f'{len(target)} of {len(uniq)} materials swapped')
