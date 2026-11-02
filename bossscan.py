#!/usr/bin/env python3
"""Find tanks and witches a map spawns by itself, on top of the boss we add from mapinfo.

    ./bossscan.py                # report every map in out/*/pkg/maps
    ./bossscan.py hauntedforest  # one campaign

rotoblin.py runs this for every map and writes out/<name>/rotoblin/bosses.txt; convert.py repeats the list at the
end of the report. It changes nothing: a map's boss can be part of its design, so each entry carries both ready
fixes and the owner picks. Run ./rotoblin.py again after flowdump.sh for game flow percentages.

Haunted Forest 1 is the case that started this: case_witch PickRandom spawned a witch on top of the rolled boss
witch, and killing it set off a panic. An info_zombie_spawn or commentary_zombie_spawner only spawns when an output
tells it to, so the check follows those outputs back to whatever starts them.
"""
import glob, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from bspinfo import lumps, ents

DEPLOY = os.path.join(os.path.dirname(HERE), 'deploy/overrides/left4dead/addons')
BOSS = re.compile(r'(?<![a-z])(tank|witch)', re.I)
MAX_HOPS = 8  # relays that fire each other in a loop must not hang the walk back


def outputs(pairs):
    """[(output, target, input, param, raw value)] for an entity's key/value pairs."""
    out = []
    for k, v in pairs:
        parts = v.split(',')
        if k.lower().startswith('on') and len(parts) >= 3:
            out.append((k, parts[0], parts[1], parts[2], v))
    return out


def kind_of(inp, param, spawners):
    """'tank', 'witch' or None for one output's input and parameter."""
    if inp.lower() == 'forcetankspawn':
        return 'tank'
    if inp.lower() == 'spawnzombie':
        m = BOSS.match(param.split(',')[0].strip()) or BOSS.search(spawners or '')
        return m.group(1).lower() if m else None
    if inp.lower() == 'command':
        m = re.search(r'z_spawn\s+(tank|witch)', param, re.I)
        return m.group(1).lower() if m else None
    return None


def scan(bsp, pct=None):
    """One dict per scripted boss in the map, with the fix lines for each. pct(position) gives flow percent."""
    import rotoblin
    d = open(bsp, 'rb').read()
    _, L = lumps(d)
    EP = ents(d, L)
    brushes = rotoblin.brush_centers(d, L)
    named = {}
    for kv, pairs in EP:
        if kv.get('targetname'):
            named.setdefault(kv['targetname'].lower(), []).append((kv, pairs))
    callers = {}
    for kv, pairs in EP:
        for o in outputs(pairs):
            callers.setdefault(o[1].lower(), []).append((kv, o))

    def roots(name, seen=()):
        """Entities with nothing firing them that lead to name, plus whether a random pick is on the way."""
        ups = [c for c in callers.get(name, []) if (c[0].get('targetname') or '').lower() not in seen]
        if not ups or len(seen) >= MAX_HOPS:
            return [], False
        found, rand = [], False
        for kv, o in ups:
            rand = rand or o[2].lower() == 'pickrandom'
            t = (kv.get('targetname') or '').lower()
            r, q = roots(t, seen + (name,)) if t else ([], False)
            found += r or [kv]
            rand = rand or q
        return found, rand

    found = {}
    for kv, pairs in EP:
        for o in outputs(pairs):
            target = o[1].lower()
            ent = named.get(target, [({}, [])])[0]
            k = kind_of(o[2], o[3], ent[0].get('population'))
            if not k:
                continue
            finale = o[2].lower() == 'forcetankspawn'
            e = found.setdefault((k, target), dict(
                kind=k, spawner=target, random=False, triggers=[], on_death=[], finale=finale, keep=[]))
            if finale or o[2].lower() == 'command':
                e['keep'].append((kv, o))
            own = (kv.get('targetname') or '').lower()
            r, q = roots(own) if own else ([], False)
            e['random'] = e['random'] or q or kv.get('classname') == 'logic_case'
            e['triggers'] += r or [kv]
            e['on_death'] = [f'{x[1]} {x[2]}' for x in outputs(ent[1]) if x[0].lower() == 'onspawnedzombiedeath']
    # A spawner nothing fires cannot spawn; listed so nobody goes looking for it (x1m1 tankster, x1m5 bridewitch).
    for kv, pairs in EP:
        m = BOSS.search(kv.get('population', '')) if kv.get('classname') == 'info_zombie_spawn' else None
        n = (kv.get('targetname') or '').lower()
        if m and (m.group(1).lower(), n) not in found:
            found[(m.group(1).lower(), n or kv.get('origin'))] = dict(
                kind=m.group(1).lower(), spawner=n or kv.get('classname'), random=False, triggers=[], on_death=[],
                finale=False, keep=[])
    out = []
    for e in found.values():
        spots = []
        for kv in e['triggers']:
            p = rotoblin.position(kv, brushes)
            spots.append((kv.get('targetname') or kv.get('classname'), kv.get('hammerid'), p,
                          pct(p) if pct and p else None))
        e['spots'] = list({(s[0], s[1]): s for s in spots}.values())
        out.append(e)
    return sorted(out, key=lambda e: (e['kind'], e['spawner']))


def fixes(m, e):
    """The two ready fixes for one boss: (remove the map's boss, turn ours off)."""
    if e['keep']:  # the entity does other work, so take away only the output
        rm = []
        for kv, o in e['keep']:
            rm += ['modify:', '{', '\tmatch:', '\t{', f'\t\t"hammerid" "{kv.get("hammerid")}"', '\t}', '\tdelete:',
                   '\t{', f'\t\t"{o[0]}" "{o[4]}"', '\t}', '}']
    else:
        rm = ['filter:', '{', f'\t"targetname" "{e["spawner"]}"', '}']
    return rm, f'"{e["kind"]}_map_off" "1"'


def handled(m, e, deploy=DEPLOY):
    """How the live config already deals with this boss, or None."""
    cfg = f'{deploy}/stripper/Roto-AZMod/maps/{m}.cfg'
    if os.path.exists(cfg):
        text = open(cfg, errors='replace').read()
        for section in re.findall(r'^filter:\s*$(.*?)(?=^(?:add|modify):\s*$|\Z)', text, re.S | re.M):
            if re.search(rf'"targetname"\s+"{re.escape(e["spawner"])}"', section, re.I):
                return 'filtered in the stripper cfg'
        if any(o[4] in text and 'delete' in text for _, o in e['keep']):
            return 'output deleted in the stripper cfg'
    info = f'{deploy}/sourcemod/data/mapinfo.txt'
    if not os.path.exists(info):
        return None
    t = open(info, errors='replace').read()
    b = re.search(rf'^\s*"{re.escape(m)}"\s*\n\s*\{{(.*?)^\t\}}', t, re.S | re.M)
    if not b:
        return None
    if re.search(rf'"{e["kind"]}_map_off"\s+"1"', b.group(1)):
        return f'{e["kind"]}_map_off 1 in mapinfo'
    ban = re.search(rf'"{e["kind"]}_ban_flow"\s*\{{(.*?)^\t\t\}}', b.group(1), re.S | re.M)
    if ban:
        wins = [(float(a), float(c)) for a, c in
                re.findall(r'"min"\s+"([\d.]+)".*?"max"\s+"([\d.]+)"', ban.group(1), re.S)]
        fl = [s[3] for s in e['spots'] if s[3] is not None]
        if fl and all(any(a <= f <= c for a, c in wins) for f in fl):
            return f'{e["kind"]}_ban_flow keeps our {e["kind"]} away from it'
    return None


def describe(m, e):
    """Report lines for one boss."""
    how = 'RANDOM, may not spawn every round; ' if e['random'] else ''
    spots = '; '.join(f'{n} at ' + (' '.join(f'{c:.0f}' for c in p) if p else 'no position')
                      + (f' ~{f}%' if f is not None else '') for n, _, p, f in e['spots'])
    if not e['triggers']:
        return [f'   {m}: unused {e["kind"]} spawner {e["spawner"]}, nothing in the map fires it']
    done = handled(m, e)
    lines = [f'{"  " if done else "!!"} {m}: scripted {e["kind"]} {e["spawner"]}'
             + (' (ForceTankSpawn on the finale)' if e['finale'] else '')
             + (f' [already handled: {done}]' if done else ''),
             f'     {how}started by {spots}']
    if e['on_death']:
        lines.append('     when it dies: ' + ', '.join(e['on_death']))
    if not done:
        rm, off = fixes(m, e)
        lines.append('     fix A, remove the map\'s boss, in the stripper cfg:')
        lines += ['         ' + x for x in rm]
        lines.append(f'     fix B, turn ours off for this map, in mapinfo: {off}')
    return lines


def report(m, bsp, pct=None):
    return [l for e in scan(bsp, pct) for l in describe(m, e)]


def main(names):
    import nav, rotoblin
    for name in names or sorted(os.path.basename(p) for p in glob.glob(HERE + '/out/*') if os.path.isdir(p + '/pkg')):
        for b in sorted(glob.glob(f'{HERE}/out/{name}/pkg/maps/*.bsp')):
            m = os.path.basename(b)[:-4]
            a = rotoblin.analyse(b, b[:-4] + '.nav', f'{HERE}/out/{name}/flowdump/{m}.txt') \
                if os.path.exists(b[:-4] + '.nav') else {}
            for l in report(m, b, a.get('pct')):
                print(l)


if __name__ == '__main__':
    main(sys.argv[1:])
