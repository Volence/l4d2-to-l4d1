#!/usr/bin/env python3
"""Downconvert an L4D2 (VBSP 21) map to L4D1 (VBSP 20).

Container: v21 lump_t is (version, ofs, len, fourCC); v20 is (ofs, len, version, fourCC).
Static props: sprp v9 is v8 plus 4 trailing bytes per record.
Entities: ESC output separators become commas, L4D2-only spawns become L4D1 ones or go away.
"""
import re, struct, sys, zlib, collections, math

W = {  # L4D1 weapon spawn classname -> (model, count)
    'weapon_smg_spawn': ('models/w_models/weapons/w_smg_uzi.mdl', '4'),
    'weapon_pumpshotgun_spawn': ('models/w_models/weapons/w_shotgun.mdl', '4'),
    'weapon_autoshotgun_spawn': ('models/w_models/weapons/w_autoshot_m4super.mdl', '5'),
    'weapon_rifle_spawn': ('models/w_models/weapons/w_rifle_m16a2.mdl', '5'),
    'weapon_hunting_rifle_spawn': ('models/w_models/weapons/w_sniper_mini14.mdl', '5'),
    'weapon_pistol_spawn': ('models/w_models/weapons/w_pistol_1911.mdl', '4'),
    'weapon_ammo_spawn': ('models/props_unique/spawn_apartment/coffeeammo.mdl', '0'),
}
SELECTION = {  # weapon_spawn weapon_selection -> candidate L4D1 classes
    'tier1_shotgun': ['weapon_pumpshotgun_spawn'],
    'any_smg': ['weapon_smg_spawn'],
    'tier1_any': ['weapon_smg_spawn', 'weapon_pumpshotgun_spawn'],
    'tier2_shotgun': ['weapon_autoshotgun_spawn'],
    'any_rifle': ['weapon_rifle_spawn'],
    'any_sniper_rifle': ['weapon_hunting_rifle_spawn'],
    'tier2_any': ['weapon_autoshotgun_spawn', 'weapon_rifle_spawn', 'weapon_hunting_rifle_spawn'],
    'any_primary': ['weapon_smg_spawn', 'weapon_pumpshotgun_spawn', 'weapon_autoshotgun_spawn',
                    'weapon_rifle_spawn', 'weapon_hunting_rifle_spawn'],
    'any_pistol': ['weapon_pistol_spawn'],
}
ITEMS = {  # weapon_item_spawn flags (L4D2 FGD) -> L4D1 class; None = no L4D1 equivalent
    'item1': 'weapon_ammo_spawn', 'item2': 'weapon_first_aid_kit_spawn', 'item3': 'weapon_molotov_spawn',
    'item4': 'weapon_pain_pills_spawn', 'item5': 'weapon_pipe_bomb_spawn',
    'item11': 'weapon_pain_pills_spawn',  # adrenaline
    'item13': 'weapon_pipe_bomb_spawn',   # bile
}
CANISTERS = {'item6': 'models/props_equipment/oxygentank01.mdl', 'item7': 'models/props_junk/propanecanister001a.mdl',
             'item8': 'models/props_junk/gascan001a.mdl'}
DROP = {'weapon_melee_spawn', 'weapon_chainsaw_spawn', 'weapon_grenade_launcher_spawn', 'upgrade_spawn',
        'weapon_rifle_m60_spawn', 'weapon_upgradepack_incendiary_spawn', 'weapon_upgradepack_explosive_spawn',
        'weapon_adrenaline_spawn', 'weapon_defibrillator_spawn', 'weapon_vomitjar_spawn', 'weapon_scavenge_item_spawn',
        'logic_script', 'info_survivor_position_l4d2'}
RENAME = {'prop_minigun_l4d1': 'prop_minigun', 'weapon_pistol_magnum_spawn': 'weapon_pistol_spawn',
          'weapon_adrenaline_spawn': 'weapon_pain_pills_spawn', 'weapon_vomitjar_spawn': 'weapon_pipe_bomb_spawn',
          # L4D2-only guns placed directly (not through weapon_spawn) become the L4D1 gun of the same tier and kind
          'weapon_smg_silenced_spawn': 'weapon_smg_spawn', 'weapon_smg_mp5_spawn': 'weapon_smg_spawn',
          'weapon_shotgun_chrome_spawn': 'weapon_pumpshotgun_spawn', 'weapon_shotgun_spas_spawn': 'weapon_autoshotgun_spawn',
          'weapon_rifle_ak47_spawn': 'weapon_rifle_spawn', 'weapon_rifle_desert_spawn': 'weapon_rifle_spawn',
          'weapon_rifle_sg552_spawn': 'weapon_rifle_spawn', 'weapon_sniper_military_spawn': 'weapon_hunting_rifle_spawn',
          'weapon_sniper_awp_spawn': 'weapon_hunting_rifle_spawn', 'weapon_sniper_scout_spawn': 'weapon_hunting_rifle_spawn'}
# func_precipitation: L4D1 knows 0 rain, 1 snow, 2 ash, 3 snowfall. L4D2's particle types (4 rain, 5 ash,
# 6 rainstorm, 7 snow) have no renderer in L4D1 and crash the client the moment it draws them (divide by zero
# in shaderapidx9.dll, Haunted Forest 2026-10-17); map each to its plain L4D1 counterpart.
PRECIP = {'4': '0', '5': '2', '6': '0', '7': '1'}
START_ROOM_RADIUS = 600
L2_KEYS = {'weapon_selection', 'spawn_without_director', 'melee_weapon', 'glowrange', 'no_cs_weapons'}
# L4D2-only inputs with an L4D1 equivalent. L4D1's info_director takes only PanicEvent and PanicEventControlled
# (server.so datadesc); a ForcePanicEvent is dropped silently, so Detour Ahead's map 2-4 events spawned no horde.
L2_INPUTS = {'forcepanicevent': 'PanicEvent'}
L2_OUTPUT_HINT = re.compile(r'runscript|callscriptfunction|scriptedpanic|setscript|scavenge|beginscript|endscript', re.I)


def pick(choices, hid):
    return choices[zlib.crc32(hid.encode()) % len(choices)]


def parse_ents(text):
    return [re.findall(r'"([^"]*)"\s+"([^"]*)"', b) for b in re.findall(r'\{(.*?)\}', text, re.S)]


def convert_entity(pairs, log):
    kv = dict(pairs)
    cls = kv.get('classname', '')
    hid = kv.get('hammerid', kv.get('origin', ''))
    new = cls
    if cls in DROP:
        log['dropped ' + cls] += 1
        return None
    if cls == 'weapon_spawn':
        new = pick(SELECTION.get(kv.get('weapon_selection', ''), ['weapon_smg_spawn']), hid)
    elif cls == 'weapon_item_spawn':
        on = [k for k, v in kv.items() if re.fullmatch(r'item\d+', k) and v not in ('0', '')]
        cands = sorted({ITEMS[k] for k in on if k in ITEMS})
        cans = [CANISTERS[k] for k in on if k in CANISTERS]
        if cands:
            new = pick(cands, hid)
        elif cans:
            new = 'prop_physics'
            pairs = [(k, v) for k, v in pairs if k in ('origin', 'angles', 'targetname', 'hammerid')]
            pairs += [('model', pick(cans, hid)), ('classname', 'prop_physics')]
            log['weapon_item_spawn -> canister'] += 1
            return pairs
        else:
            log['dropped weapon_item_spawn (no L4D1 item)'] += 1
            return None
    elif cls == 'weapon_gascan_spawn':  # L4D1 places gas cans as plain physics props
        pairs = [(k, v) for k, v in pairs if k in ('origin', 'angles', 'targetname', 'hammerid')]
        log['weapon_gascan_spawn -> canister'] += 1
        return pairs + [('model', CANISTERS['item8']), ('classname', 'prop_physics')]
    elif cls in RENAME:
        new = RENAME[cls]
    out = []
    for k, v in pairs:
        if k in L2_KEYS or re.fullmatch(r'item\d+', k):
            continue
        v = v.replace('\x1b', ',')
        p = v.split(',')
        if k.lower().startswith(('on', 'out')) and len(p) > 1 and p[1].lower() in L2_INPUTS:
            log[f'input {p[1]} -> {L2_INPUTS[p[1].lower()]}'] += 1
            v = ','.join([p[0], L2_INPUTS[p[1].lower()]] + p[2:])
        if L2_OUTPUT_HINT.search(v) and k.lower().startswith('on'):
            log['stripped script/scavenge output'] += 1
            continue
        if k == 'classname':
            v = new
        if cls == 'func_precipitation' and k.lower() == 'preciptype' and v in PRECIP:
            log[f'func_precipitation type {v} -> {PRECIP[v]}'] += 1
            v = PRECIP[v]
        # Ajar doors (spawnpos 3) never move in L4D1, not even on ent_fire Open (Carried Off 2 at 8836 4228
        # 336 blocked the route); Valve's 758 L4D1 doors never start ajar. Start them closed instead.
        if cls.startswith('prop_door_rotating') and k.lower() == 'spawnpos' and v == '3':
            log['ajar door -> closed'] += 1
            v = '0'
        out.append((k, v))
    # renderamt does nothing under rendermode 0, so mappers leave stray values (Detour Ahead: hittable cars at 100).
    # Rotoblin's l4d_tank_props restores a hittable's colour with RENDER_TRANSCOLOR forced on after a tank, which
    # turns that alpha on: whole streets of cars went see-through. Same look in L4D2, safe under that plugin.
    if new.startswith('prop_') and dict(out).get('rendermode', '0') == '0' and dict(out).get('renderamt', '255') != '255':
        out = [(k, '255' if k == 'renderamt' else v) for k, v in out]
        log['renderamt -> 255 (rendermode 0)'] += 1
    if new in W:
        model, count = W[new]
        out = [(k, v) for k, v in out if k != 'model'] + [('model', model)]
        if not any(k == 'count' for k, _ in out):
            out.append(('count', count))
    if new != cls:
        log[f'{cls} -> {new}'] += 1
    return out


def fog_volumes_to_triggers(ents, log):
    """L4D2 picks a player's fog controller by fog_volume; L4D1 has no fog_volume and keeps the master fog
    everywhere. Detour Ahead 4's bridge uses a thick fog that hides where an area portal window stops
    drawing; under the master fog that cutoff showed as black sky with the trains gone. A trigger that
    sends !activator SetFogController (a CBasePlayer input L4D1 has) on entry, and the master on exit,
    does the same job."""
    fogs = [dict(e) for e in ents if dict(e).get('classname') == 'env_fog_controller' and dict(e).get('targetname')]
    if not fogs:
        return ents
    master = next((f for f in fogs if int(f.get('spawnflags', '0') or 0) & 1), fogs[0])['targetname']
    out = []
    for e in ents:
        kv = dict(e)
        if kv.get('classname') != 'fog_volume' or not kv.get('FogName') or not kv.get('model'):
            out.append(e)
            continue
        if kv.get('StartDisabled', '0') != '0':
            log['dropped disabled fog_volume'] += 1
            continue
        out.append([('classname', 'trigger_multiple'), ('model', kv['model']), ('spawnflags', '1'), ('wait', '0'),
                    ('StartDisabled', '0'), ('origin', kv.get('origin', '0 0 0')),
                    ('OnStartTouch', f'!activator,SetFogController,{kv["FogName"]},0,-1'),
                    ('OnEndTouch', f'!activator,SetFogController,{master},0,-1')])
        log['fog_volume -> fog trigger'] += 1
    return out


def write_ents(ents):
    s = ''.join('{\n' + ''.join(f'"{k}" "{v}"\n' for k, v in e) + '}\n' for e in ents)
    return s.encode('latin1') + b'\0'


def convert(src, dst, drop_models=()):
    d = open(src, 'rb').read()
    assert d[:4] == b'VBSP' and struct.unpack('<i', d[4:8])[0] == 21, 'not a v21 BSP'
    L = [struct.unpack('<iiii', d[8 + 16 * i:24 + 16 * i]) for i in range(64)]  # ver, ofs, len, cc
    rev = struct.unpack('<i', d[1032:1036])[0]
    data = {i: d[o:o + n] for i, (v, o, n, cc) in enumerate(L)}
    log = collections.Counter()

    ents = [e for e in (convert_entity(p, log) for p in parse_ents(data[0].decode('latin1'))) if e]
    ents = fog_volumes_to_triggers(ents, log)
    # A never-solid func_brush whose brush model has no faces draws and blocks nothing, yet in L4D1 it stops
    # the frame drawing: Detour Ahead 4's "bridgeap1" (model *160, 0 faces) blacked out the sky and every
    # static prop whenever it was in view (found by clienttest/propbisect.py ents). Drop such brushes.
    faces = [struct.unpack('<i', data[14][48 * m + 44:48 * m + 48])[0] for m in range(len(data[14]) // 48)]
    def empty_brush(e):
        kv = dict(e)
        mdl = kv.get('model', '')
        return (kv.get('classname') == 'func_brush' and kv.get('Solidity') == '1' and mdl.startswith('*')
                and mdl[1:].isdigit() and int(mdl[1:]) < len(faces) and faces[int(mdl[1:])] == 0)
    dropped = [e for e in ents if empty_brush(e)]
    if dropped:
        log['dropped faceless never-solid func_brush'] += len(dropped)
        gone = {dict(e).get('targetname') for e in dropped} - {None}
        ents = [e for e in ents if not empty_brush(e)]
        # They are the fade brushes of func_areaportalwindows (bridgeap1 is window 17's target). Without a
        # target the server leaves the window's background model unset and the client draws no fade brush;
        # the portal still opens and closes by distance. (Valve's 680 L4D1 windows all have drawable targets.)
        ents = [[(k, v) for k, v in e if not (k == 'target' and v in gone and dict(e).get('classname') == 'func_areaportalwindow')]
                for e in ents]
    # L4D1's director culls weapon spawns without "Must Exist" (spawnflag 2); L4D2 start rooms often
    # leave it off, so the start-room guns vanish. Force it on near the player start.
    pos = lambda e: [float(x) for x in dict(e).get('origin', '0 0 0').split()]
    starts = [pos(e) for e in ents if dict(e).get('classname') == 'info_player_start']
    for i, e in enumerate(ents):
        kv = dict(e)
        if kv.get('classname') in W and starts and min(math.dist(pos(e), s) for s in starts) < START_ROOM_RADIUS:
            flags = int(kv.get('spawnflags', '0')) | 2
            if str(flags) != kv.get('spawnflags'):
                ents[i] = [(k, v) for k, v in e if k != 'spawnflags'] + [('spawnflags', str(flags))]
                log['start-room spawn set Must Exist'] += 1
    data[0] = write_ents(ents)

    # HDR-only lighting (lump 8 empty) renders the world unlit on mat_hdr_level 0. Both lightmap lumps hold
    # the same ColorRGBExp32 texels, so the HDR set stands in: lightmaps 53->8, the faces that point into
    # them 58->7 (same face list, real lightofs) and the light list 54->15.
    if not data[8] and data[53] and len(data[58]) == len(data[7]):
        for ldr, hdr in ((8, 53), (7, 58), (15, 54)):
            if data[hdr]:
                data[ldr] = data[hdr]
                L[ldr] = (L[hdr][0],) + L[ldr][1:]
        log['LDR lighting filled from HDR'] += 1

    # game lump: rewrite sprp v9 -> v8; offsets are absolute and fixed up after layout
    g = data[35]
    n = struct.unpack('<i', g[:4])[0]
    heads = [list(struct.unpack('<iHHii', g[4 + 16 * i:20 + 16 * i])) for i in range(n)]
    bodies = []
    for h in heads:
        body = d[h[3]:h[3] + h[4]]
        if h[0] == int.from_bytes(b'sprp', 'big') and h[2] == 9:
            nd = struct.unpack('<i', body[:4])[0]
            p = 4 + 128 * nd
            nl = struct.unpack('<i', body[p:p + 4])[0]
            p += 4 + 2 * nl
            npr = struct.unpack('<i', body[p:p + 4])[0]
            p += 4
            assert len(body) - p == 72 * npr, 'unexpected sprp v9 size'
            names = [body[4 + 128 * i:132 + 128 * i] for i in range(nd)]
            keep = [i for i, nm in enumerate(names)
                    if not nm.split(b'\0')[0].decode('latin1').lower().startswith(tuple(drop_models))]
            remap = {old: new for new, old in enumerate(keep)}
            recs = []
            for i in range(npr):
                rec = bytearray(body[p + 72 * i:p + 72 * i + 68])
                ptype = struct.unpack_from('<H', rec, 24)[0]
                if ptype not in remap:
                    log[f'dropped static prop {names[ptype].split(b"\0")[0].decode()}'] += 1
                    continue
                struct.pack_into('<H', rec, 24, remap[ptype])
                recs.append(bytes(rec))
            leaves = body[4 + 128 * nd:4 + 128 * nd + 4 + 2 * nl]
            body = (struct.pack('<i', len(keep)) + b''.join(names[i] for i in keep) + leaves
                    + struct.pack('<i', len(recs)) + b''.join(recs))
            h[2] = 8
            log[f'static props v9->v8 ({npr})'] += 1
        bodies.append(body)

    # layout: header then lumps in original file order, 4-byte aligned
    order = sorted(range(64), key=lambda i: L[i][1])
    out = bytearray(1036)
    newL = {}
    for i in order:
        while len(out) % 4:
            out += b'\0'
        if i == 35:
            base = len(out) + 4 + 16 * n
            hdr = struct.pack('<i', n)
            pos = base
            for h, b in zip(heads, bodies):
                hdr += struct.pack('<iHHii', h[0], h[1], h[2], pos, len(b))
                pos += len(b)
            blob = hdr + b''.join(bodies)
        else:
            blob = data[i]
        newL[i] = (len(out), len(blob)) if blob else (0, 0)
        out += blob
    out[0:8] = b'VBSP' + struct.pack('<i', 20)
    for i in range(64):
        o, ln = newL[i]
        out[8 + 16 * i:24 + 16 * i] = struct.pack('<iiii', o, ln, L[i][0], L[i][3])
    out[1032:1036] = struct.pack('<i', rev)
    open(dst, 'wb').write(out)
    return log


if __name__ == '__main__':
    for log_line in sorted(convert(sys.argv[1], sys.argv[2], tuple(sys.argv[3:])).items()):
        print(f'  {log_line[1]:4d}  {log_line[0]}')
