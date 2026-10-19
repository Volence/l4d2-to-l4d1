#!/usr/bin/env python3
"""Run a harness-style .steps file in the private client ~/l4d1-dt-client, never the owner's game.

    dtclient.py <steps> <outdir>

Steps: map NAME [mode] | cmd TEXT | sleep SECS | shot NAME. Launches through Proton with its own
prefix (l4dsrc.client_launch), drives it over netcon, converts each screenshot to PNG, quits.
Built 2026-10-19 because Steam would not -applaunch the owner's install while another agent's client ran.
"""
import sys
sys.path = [p for p in sys.path if not p.rstrip("/").endswith("clienttest")]  # clienttest/bisect.py shadows stdlib bisect
import os, secrets, shutil, subprocess, time
from pathlib import Path
sys.path.insert(0, '/home/volence/l4d/source/tools')
from l4dsrc import client_launch as cl

INSTALL = Path.home() / 'l4d1-dt-client'
G = INSTALL / 'left4dead'


def ours():
    return [p for p in os.popen("pgrep -f 'l4d1-dt-client/left4dead.exe'").read().split()]


def main(steps, out):
    out = Path(out); shutil.rmtree(out, ignore_errors=True); out.mkdir(parents=True)
    if ours():
        sys.exit('dt client already running')
    port, pw = 27600 + secrets.randbelow(300), 'dt' + secrets.token_hex(6)
    log = G / 'console.log'
    if log.exists(): log.unlink()
    cl.ensure_prefix(INSTALL)
    proc = subprocess.Popen(cl.build_command(INSTALL, port, pw), env=cl.build_env(INSTALL), cwd=INSTALL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    try:
        if not cl._wait(lambda: cl._probe(port, pw), cl.UP_TIMEOUT):
            sys.exit('console never came up')
        for line in open(steps):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            op, _, arg = line.partition(' ')
            if op == 'map':
                name, *mode = arg.split()
                before = log.read_text(errors='replace').count('Redownloading all lightmaps') if log.exists() else 0
                cl._send(port, pw, f'mp_gamemode {mode[0] if mode else "coop"}; sv_cheats 1; map {name}')
                cl._wait(lambda: log.exists() and log.read_text(errors='replace').count('Redownloading all lightmaps') > before, 180)
                time.sleep(4)
            elif op == 'cmd':
                cl._send(port, pw, arg)
            elif op == 'sleep':
                time.sleep(float(arg))
            elif op == 'shot':
                shots = G / 'screenshots'
                stamp = time.time()
                cl._send(port, pw, f'screenshot {arg}')
                cl._wait(lambda: any(p.stat().st_mtime >= stamp for p in shots.glob(f'{arg}*.tga')), 20, 0.5)
                time.sleep(1)
                tga = max(shots.glob(f'{arg}*.tga'), key=lambda p: p.stat().st_mtime, default=None)
                if tga:
                    subprocess.run(['magick', str(tga), str(out / f'{arg}.png')])
                    tga.unlink()
        shutil.copy(log, out / 'console.log') if log.exists() else None
    finally:
        try:
            cl._send(port, pw, 'quit', read=0.5)
        except Exception:
            pass
        time.sleep(5)
        for p in ours():
            subprocess.run(['kill', p])


if __name__ == '__main__':
    main(*sys.argv[1:3])
