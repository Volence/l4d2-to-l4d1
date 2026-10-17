#!/usr/bin/env python3
"""Generate starter Rotoblin-AZMod files for converted maps.

    ./rotoblin.py out/<name>/pkg            (convert.py runs this for you)

Writes out/<name>/rotoblin/:
  mapinfo.txt          one block per map, to paste into deploy/overrides/.../data/mapinfo.txt
  stripper/<map>.cfg   per-map stripper config in Harry's section layout, to drop into
                       deploy/overrides/left4dead/addons/stripper/Roto-AZMod/maps/
  flow.txt             the flow estimate per map: start, end, events, start-room items

Flow comes from out/<name>/flowdump/<map>.txt (the game's own per-area flow, made by flowdump.sh)
when it exists. Without it, flow is a rough nav ESTIMATE (shortest walk; measured 0.4-1.0x of the
real length on stock maps), labelled as such. Either way, check ban windows in game with !cur, and
confirm map length in a round with a human: an empty server misreads some maps (stock DA-4, NM-4).
"""
import glob, heapq, json, math, os, re, struct, sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from bspinfo import lumps, ents, lump
import nav

BOSS_BUFFER = 2200          # versus_boss_buffer: the engine spawns the tank this far before the stored flow
LATEST_TANK = 90            # Riverside rule: latest tank trigger at 90% of the map (match 363 door camp)
GLOBAL_BOSS_MAX = 80        # versus_boss_flow_max in deploy local_4v4.cfg; our boss fork forces a tank and
                            # witch on EVERY map between 10% and this, so a map only needs a cap if stricter
START_ROOM = 600            # units from info_player_start that count as the start saferoom
BAN_BEFORE, BAN_AFTER = 5, 15  # default window around an event, in flow %
PANIC = re.compile(r'(force|scripted)?panicevent', re.I)


def brush_centers(d, L):
    """Brush model '*N' -> center of its bounds (brush entities have no origin key)."""
    b = lump(d, L, 14)
    out = {}
    for i in range(len(b) // 48):
        mn, mx = struct.unpack_from('<3f', b, 48 * i), struct.unpack_from('<3f', b, 48 * i + 12)
        out[f'*{i}'] = tuple((x + y) / 2 for x, y in zip(mn, mx))
    return out


def position(kv, brushes):
    if kv.get('origin') and kv['origin'].strip() not in ('0 0 0', ''):
        p = tuple(float(x) for x in kv['origin'].split())
        if kv.get('model', '').startswith('*'):  # brush entity with an origin: bounds are relative
            p = tuple(a + b for a, b in zip(p, brushes.get(kv['model'], (0, 0, 0))))
        return p
    return brushes.get(kv.get('model', ''))


def flow_map(areas, ladders, start, end):
    """Shortest walk from the area nearest start, over nav connections and ladders.

    Elevators and scripted lifts have no nav link, so when the walk cannot reach the end it bridges the
    gap: it joins the unreached area closest to anything reached and keeps going. Returns id -> distance.
    """
    by_id = {a['id']: a for a in areas}
    edges = {a['id']: [(j, None) for j in a['conns'] if j in by_id] for a in areas}
    for bottom, tops, length in ladders:
        for t in tops:
            if bottom in by_id and t in by_id:
                edges[bottom].append((t, length)); edges[t].append((bottom, length))
    src = min(areas, key=lambda a: math.dist(a['center'], start))['id']
    goal = min(areas, key=lambda a: math.dist(a['center'], end))['id'] if end else None
    dist = {src: 0.0}
    q = [(0.0, src)]
    ids = np.array([a['id'] for a in areas])
    xyz = np.array([a['center'] for a in areas])
    for _ in range(50):
        while q:
            dd, i = heapq.heappop(q)
            if dd > dist[i]:
                continue
            for j, w in edges[i]:
                nd = dd + (w if w is not None else math.dist(by_id[i]['center'], by_id[j]['center']))
                if nd < dist.get(j, 1e18):
                    dist[j] = nd; heapq.heappush(q, (nd, j))
        if goal is None or goal in dist:
            break
        reached = np.array([i in dist for i in ids])
        R, U = xyz[reached], xyz[~reached]
        best = (1e18, None, None)
        for k in range(0, len(U), 2048):
            dm = np.linalg.norm(U[k:k + 2048, None, :] - R[None, :, :], axis=2)
            ui, ri = np.unravel_index(dm.argmin(), dm.shape)
            if dm[ui, ri] < best[0]:
                best = (dm[ui, ri], ids[~reached][k + ui], ids[reached][ri])
        gap, u, r = best
        dist[u] = dist[r] + gap
        heapq.heappush(q, (dist[u], u))
    return dist


def nearest_reached(areas, dist, p):
    reach = [a for a in areas if a['id'] in dist]
    a = min(reach, key=lambda a: math.dist(a['center'], p))
    return a, dist[a['id']]


def load_flowdump(path):
    """(maxflow, {area id: flow}) from a flowdump file, or None."""
    if not os.path.exists(path):
        return None
    lines = open(path).read().split('\n')
    maxflow = float(lines[0].split()[1])
    flows = {int(i): float(f) for i, f in (l.split() for l in lines[1:] if l.strip())}
    return maxflow, flows


def analyse(bsp, navfile, flowfile=None, scripts=()):
    d = open(bsp, 'rb').read(); ver, L = lumps(d)
    EP = ents(d, L)  # (dict, pairs): outputs repeat keys, so scan the pairs
    E = [kv for kv, _ in EP]
    brushes = brush_centers(d, L)
    areas, ladders = nav.mesh(open(navfile, 'rb').read())
    names = {}
    for kv in E:
        if kv.get('targetname'):
            names.setdefault(kv['targetname'].lower(), []).append(kv)
    # start: info_player_start, else the nav's PLAYER_START areas, else the survivor positions
    starts = [position(kv, brushes) for kv in E if kv.get('classname') == 'info_player_start']
    if not starts:
        starts = [a['center'] for a in areas if a['spawn'] & 0x80]
    if not starts:
        starts = [position(kv, brushes) for kv in E if kv.get('classname') == 'info_survivor_position']
    start = tuple(np.mean([p for p in starts if p], axis=0))
    ends = [p for p in (position(kv, brushes) for kv in E if kv.get('classname') == 'info_changelevel') if p]
    if not ends:  # finale or odd map: the CHECKPOINT nav area farthest from the start
        cps = [a['center'] for a in areas if a['spawn'] & 0x800 and math.dist(a['center'], start) > START_ROOM]
        ends = [max(cps, key=lambda c: math.dist(c, start))] if cps else []
    end = ends[0] if ends else None
    game = load_flowdump(flowfile) if flowfile else None
    if game and game[0] > 0:
        source = 'game flow (flowdump)'
        maxflow = game[0]
        dist = {i: f for i, f in game[1].items() if f >= 0}
    else:
        source = 'NAV ESTIMATE' + (' (flowdump read max flow 0: measure in a live round)' if game else '')
        dist = flow_map(areas, ladders, start, end)
        maxflow = nearest_reached(areas, dist, end)[1] if end else max(dist.values())
        if maxflow <= 0:  # the end sits beside the start or off the walkable graph (x1m6_aftermath): use the farthest area
            source += ', end not reached, farthest area used'
            maxflow = max(dist.values())
    pct = lambda p: round(100 * nearest_reached(areas, dist, p)[1] / maxflow, 1)

    events = []
    directors = {kv.get('targetname', '').lower() for kv in E if kv.get('classname') == 'info_director'}
    directors |= {'@director', 'director', '!director'}
    for kv, pairs in EP:
        for k, v in pairs:
            if not k.lower().startswith('on'):
                continue
            parts = re.split(r'[,\x1b]', v)
            if len(parts) >= 2 and parts[0].lower() in directors and PANIC.search(parts[1]):
                p = position(kv, brushes)
                if p:
                    label = kv.get('targetname') or kv.get('classname')
                    events.append(('Panic Event', label, p))
        c = kv.get('classname', '')
        if c in ('func_elevator', 'func_tracktrain') and position(kv, brushes):
            events.append(('Elevator' if c == 'func_elevator' else 'Moving platform',
                           kv.get('targetname') or c, position(kv, brushes)))
        if c == 'trigger_finale' and position(kv, brushes):
            events.append(('Finale', kv.get('targetname') or c, position(kv, brushes)))
    alarms = [position(kv, brushes) for kv in E if kv.get('classname') == 'prop_car_alarm']
    seen, ev = set(), []
    for kind, label, p in events:
        f = pct(p)
        key = (kind, round(f))
        if key not in seen:
            seen.add(key); ev.append((f, kind, label, p))
    ev.sort()

    near_start = lambda kv: position(kv, brushes) and math.dist(position(kv, brushes), start) < START_ROOM
    start_items = [(kv['classname'], position(kv, brushes)) for kv in E
                   if kv.get('classname', '').startswith('weapon_') and near_start(kv)]
    ammo_spot = None
    if not any(c == 'weapon_ammo_spawn' for c, _ in start_items):
        guns = [p for c, p in start_items if c not in ('weapon_first_aid_kit_spawn', 'weapon_pain_pills_spawn')]
        target = guns[0] if guns else start
        # the walkable floor beside the guns: center of the nearest nav area that is not under them
        cands = [a for a in areas if math.dist(a['center'], start) < START_ROOM
                 and math.dist(a['center'][:2], target[:2]) > 24]
        if cands:
            ammo_spot = min(cands, key=lambda a: math.dist(a['center'], target))['center']
    # Director Scripts: a "*nobosses*" script switched on at a trigger means no bosses until its
    # EndScript (or the end of the map). L4D1 lost the script, so express it as ban windows.
    sc = sorted((pct(p), kind, name, label) for kind, name, label, p in scripts)
    noboss, lost = [], []
    for f, kind, name, label in sc:
        if kind == 'begin' and re.search(r'no_?boss', name, re.I):
            stop = next((g for g, k2, _, _ in sc if k2 == 'end' and g > f), 100.0)
            noboss.append((f, stop, name, label))
        elif kind == 'begin':
            lost.append((f, name, label))
    return dict(start=start, end=end, maxflow=maxflow, source=source, noboss=noboss, lost_scripts=lost, events=ev, alarms=[(pct(p), p) for p in alarms if p],
                start_items=start_items, ammo_spot=ammo_spot)


def fmt(p):
    return ' '.join(str(round(x)) for x in p)


def mapinfo_block(m, a, modifier):
    buf = 100 * BOSS_BUFFER / a['maxflow']
    lines = [f'\t"{m}"', '\t{',
             '\t\t"pill_limit"\t\t"2"',
             f'\t\t"VersusModifier"\t\t"{modifier}" // from the mission\'s VersusCompletionScore / 400']
    cap = math.floor(LATEST_TANK - buf)
    if cap < GLOBAL_BOSS_MAX:  # short map: the global cap would let the tank reach the saferoom door
        lines.append(f'\t\t"versus_boss_flow_max"\t"{cap}" // {LATEST_TANK} minus boss buffer {buf:.1f}% '
                     f'(max flow {a["maxflow"]:.0f}, {a["source"]}); keeps the tank off the saferoom door')
    bans = [(f'{kind} {label}', max(0, round(f - BAN_BEFORE)), min(100, round(f + BAN_AFTER)),
             f'event starts ~{f}% ({a["source"]})') for f, kind, label, p in a['events'] if kind != 'Finale']
    # The author's no-boss Director Scripts never apply on our servers (the boss fork forces bosses on
    # every map, and L4D1 has no VScript anyway). They are written commented out as a hint of where the
    # author did not want a tank; remove the // only if you agree.
    noboss = [(f'No bosses ({name})', math.floor(f), math.ceil(g),
               f"author's Director Script, trigger {label}", True) for f, g, name, label in a['noboss']]
    bans = [b + (False,) for b in bans]
    for key, wins in (('tank_ban_flow', bans + noboss), ('witch_ban_flow', noboss)):
        if not wins:
            continue
        on = any(not off for *_, off in wins)
        c = '' if on else '//'
        lines += [f'\t\t{c}"{key}"', f'\t\t{c}{{']
        for name, lo, hi, note, off in wins:
            k = '//' if off else ''
            lines += [f'\t\t\t{k}"{name}"', f'\t\t\t{k}{{', f'\t\t\t\t{k}"min"\t\t"{lo}"',
                      f'\t\t\t\t{k}"max"\t\t"{hi}" // {note}', f'\t\t\t{k}}}']
        lines += [f'\t\t{c}}}']
    lines += ['\t}']
    return '\n'.join(lines)


SECTIONS = [
    ('DIRECTOR AND EVENT CHANGES', [('DIRECTOR & EVENT MODIFICATION', 'Modify director behaviour and events')]),
    ('ITEM SPAWN CHANGES', [('PILL / ITEM / WEAPON SPAWNS', 'Remove or change pill, item & weapon spawns'),
                            ('STATIC AMMO PILES', 'Add or modify ammo pile spawns'),
                            ('HITTABLE CHANGES', 'Add/remove/modify hittables')]),
    ('MAP CLIPPING AND ISSUES', [('EXPLOITS BLOCKED', 'Block intentionally performed exploits'),
                                 ('OUT OF BOUNDS', 'Block players getting outside / under the map'),
                                 ('STUCK SPOTS', 'Prevent players from getting stuck in the map')]),
    ('NAV AREA BUGS / INFECTED ACCESS', [('INFECTED LADDERS', 'Add or remove infected ladders'),
                                          ('LOS / COVER', 'Props for infected cover or survivor LOS')]),
]


def stripper_cfg(m, title, a):
    out = [f'; {m}: {title}', '; Generated by l4d2to1/rotoblin.py, then edited by hand. Positions below are',
           f'; from the BSP and {a["source"]}; check them in game with getpos / !cur.', ';',
           f'; start (info_player_start) {fmt(a["start"])}',
           f'; end (info_changelevel)    {fmt(a["end"]) if a["end"] else "none (finale)"}',
           f'; max flow                  {a["maxflow"]:.0f}']
    for f, kind, label, p in a['events']:
        out.append(f'; {kind:<18s} ~{f:5.1f}%  {label}  at {fmt(p)}')
    for f, p in a['alarms']:
        out.append(f'; car alarm          ~{f:5.1f}%  at {fmt(p)}')
    for f, g, name, label in a['noboss']:
        out.append(f'; no bosses          ~{f:5.1f}% to ~{g:5.1f}%  ({name}, now mapinfo ban windows)')
    for f, name, label in a['lost_scripts']:
        out.append(f'; !! Director Script {name} at ~{f:5.1f}% ({label}) has no L4D1 equivalent: rebuild by hand')
    out.append(';')
    for big, subs in SECTIONS:
        out += ['', '; ' + '#' * 53, f'; {"### " + big + " ###":^53s}', '; ' + '#' * 53]
        for head, desc in subs:
            out += ['; ' + '=' * 53, f'; =={head:^49s}==', f'; =={desc:^49s}==', '; ' + '=' * 53]
            if head == 'STATIC AMMO PILES' and a['ammo_spot']:
                x, y, z = a['ammo_spot']
                out += ['; ---- start saferoom has no ammo pile: add one on the floor beside the guns',
                        '; (auto-placed on the nearest walkable nav area; move it if it clips furniture)',
                        'add:', '{', '\t"classname" "weapon_ammo_spawn"',
                        f'\t"origin" "{round(x)} {round(y)} {round(z)}"', '\t"angles" "0 0 0"',
                        '\t"model" "models/props_unique/spawn_apartment/coffeeammo.mdl"',
                        '\t"solid" "6"', '\t"spawnflags" "2"', '\t"disableshadows" "1"', '}']
    return '\n'.join(out) + '\n'


def mission_info(pkg):
    """(map -> (title, VersusModifier)) from the converted mission file."""
    res = {}
    for mf in glob.glob(pkg + '/missions/*.txt'):
        t = open(mf, encoding='latin1').read()
        title = (re.search(r'"DisplayTitle"\s+"([^"]+)"', t) or re.search(r'"Name"\s+"([^"]+)"', t)).group(1)
        vs = t[t.lower().find('"versus"'):]
        for blk in re.finditer(r'"Map"\s+"([^"]+)"(.*?)(?="Map"|\Z)', vs, re.S):
            mod = re.search(r'"VersusModifier"\s+"([\d.]+)"', blk.group(2))
            res[blk.group(1).lower()] = (title, mod.group(1) if mod else '1.0')
    return res


def main(pkg):
    outdir = os.path.join(os.path.dirname(os.path.abspath(pkg)), 'rotoblin')
    os.makedirs(outdir + '/stripper', exist_ok=True)
    info = mission_info(pkg)
    sj = os.path.join(os.path.dirname(outdir), 'director_scripts.json')
    scripts = json.load(open(sj)) if os.path.exists(sj) else {}
    blocks, flows = [], []
    for b in sorted(glob.glob(pkg + '/maps/*.bsp')):
        m = os.path.basename(b)[:-4]
        n = b[:-4] + '.nav'
        if not os.path.exists(n):
            print(f'!! {m}: no nav, skipped'); continue
        a = analyse(b, n, os.path.join(os.path.dirname(outdir), 'flowdump', m + '.txt'), scripts.get(m, ()))
        title, mod = info.get(m, (m, '1.0'))
        blocks.append(mapinfo_block(m, a, mod))
        open(f'{outdir}/stripper/{m}.cfg', 'w').write(stripper_cfg(m, title, a))
        flows.append(f'{m}: max flow {a["maxflow"]:.0f} ({a["source"]}), {len(a["events"])} events, '
                     f'start items {[c for c, _ in a["start_items"]]}, '
                     f'ammo added: {"yes" if a["ammo_spot"] else "no (already has one)"}')
        head = len(flows) - 1
        for f, kind, label, p in a['events']:
            flows.append(f'    {kind} {label} ~{f}%')
        for f, g, name, label in a['noboss']:
            flows.append(f'    no bosses ({name}) ~{f}% to ~{g}%')
        for f, name, label in a['lost_scripts']:
            flows.append(f'    !! lost Director Script {name} ~{f}%')
        print('\n'.join(flows[head:]))
    open(outdir + '/mapinfo.txt', 'w').write(
        '// Generated by l4d2to1/rotoblin.py: paste inside "MapInfo" in\n'
        '// deploy/overrides/left4dead/addons/sourcemod/data/mapinfo.txt. Ban windows are TRUE flow\n'
        '// (Riverside realflow fork). Each block says whether its numbers are game flow or a nav\n'
        '// estimate; verify every window with !cur in game.\n\n'
        + '\n'.join(blocks) + '\n')
    open(outdir + '/flow.txt', 'w').write('\n'.join(flows) + '\n')
    return outdir


if __name__ == '__main__':
    print(main(sys.argv[1]))
