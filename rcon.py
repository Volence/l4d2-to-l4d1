#!/usr/bin/env python3
"""Minimal Source RCON client: rcon.py host port password cmd [cmd ...]"""
import socket, struct, sys, time


def pkt(i, t, body):
    b = body.encode() + b'\0\0'
    return struct.pack('<iii', len(b) + 8, i, t) + b


def main(host, port, pw, *cmds):
    s = socket.create_connection((host, int(port)), timeout=10)

    def recv():
        h = b''
        while len(h) < 4:
            h += s.recv(4 - len(h))
        n = struct.unpack('<i', h)[0]; d = b''
        while len(d) < n:
            d += s.recv(n - len(d))
        return d

    s.sendall(pkt(1, 3, pw)); recv(); r = recv()
    if struct.unpack('<i', r[:4])[0] == -1:
        sys.exit('rcon auth failed')
    for c in cmds:
        s.sendall(pkt(2, 2, c)); time.sleep(0.6); s.settimeout(1); out = b''
        try:
            while True:
                out += recv()[8:-2]
        except OSError:
            pass
        s.settimeout(10); print(out.decode('latin1'))


if __name__ == '__main__':
    main(*sys.argv[1:])
