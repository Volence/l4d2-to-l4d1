#!/usr/bin/env python3
"""Convert an L4D2 custom campaign into an L4D1 addon VPK.

    ./convert.py path/to/campaign.zip|.vpk [--name NAME] [--drop-models PREFIX ...] [--no-dict] [--no-comp] [--no-verify]

Writes out/<name>/report.txt and out/<name>/<name>_l4d1.vpk, then runs dictbuild.sh so every map carries an
L4D1 string table dictionary (without one a SourceTV demo can crash the server; see dictfix.py). Maps that SirPlease's
L4D2-Competitive-Rework has a zonemod stripper cfg for get it ported (compstripper.py) into out/<name>/rotoblin/stripper/,
and stripverify.sh loads each of those maps on the strip rig and checks the result. Read the report before playing:
it lists VScript use, entities with no L4D1 equivalent and assets that could not be found.
See README.md for what each step does and why.
"""
import argparse, collections, glob, io, json, os, pickle, re, shutil, struct, subprocess, sys, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import vpkread
import waterfix
from bspinfo import lumps, ents, texdata, staticprops, pak
import compstripper, l4d2to1, nav2to1, rotoblin

STEAM = os.path.expanduser('~/.local/share/Steam/steamapps/common')
L4D1 = f'{STEAM}/left 4 dead'
L4D2 = f'{STEAM}/Left 4 Dead 2'
L4D1_SERVER_SO = '/home/volence/l4d1-ds/server/left4dead/bin/server.so'
# L4D2 models that crash the L4D1 client (studiorender.dll access violation, 2026-10-08, CCR map 1).
DEFAULT_DROP = ('models/deadbodies/',)
VENV = os.path.join(HERE, '.venv')


def vpk_index(path):
    f, base, es = vpkread.entries(path)
    return {p.lower(): (path, base, arc, off, ln, pre) for p, arc, off, ln, pre in es}


def vpk_read(entry):
    path, base, arc, off, ln, pre = entry
    if arc == 0x7fff:
        f = open(path, 'rb'); f.seek(base + off)
    else:
        f = open(path.replace('_dir.vpk', '_%03d.vpk' % arc), 'rb'); f.seek(off)
    return pre + f.read(ln)


def indexes(cache):
    """Files L4D1 players already have (base game + our zz_l4d2maps pack), and the L4D2 install."""
    if os.path.exists(cache):
        return pickle.load(open(cache, 'rb'))
    have = set()
    for p in [f'{L4D1}/left4dead/pak01_dir.vpk', f'{L4D1}/left4dead_dlc3/pak01_dir.vpk',
              f'{L4D1}/hl2/hl2_misc_dir.vpk', f'{L4D1}/hl2/hl2_textures_dir.vpk',
              *glob.glob(f'{L4D1}/left4dead/addons/*l4d2maps_*.vpk')]:
        if os.path.exists(p):
            have |= set(vpk_index(p))
    l2 = {}
    for p in sorted(glob.glob(f'{L4D2}/*/pak01_dir.vpk')):
        l2.update(vpk_index(p))
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    pickle.dump((have, l2), open(cache, 'wb'))
    return have, l2


def extract(src, dest):
    """Unpack the campaign (zip containing VPKs, a bare VPK, or loose files) into dest."""
    vpks = []
    if src.endswith('.zip'):
        try:
            with zipfile.ZipFile(src) as z:
                z.extractall(dest + '/_zip')
        except NotImplementedError:  # Deflate64 and friends (the sirplease.net zips): Python can't, 7z can
            subprocess.run(['7z', 'x', '-y', '-o' + dest + '/_zip', src], check=True, stdout=subprocess.DEVNULL)
        vpks = glob.glob(dest + '/_zip/**/*.vpk', recursive=True)
    elif src.endswith('.vpk'):
        vpks = [src]
    for v in vpks:
        idx = vpk_index(v)
        for name, e in idx.items():
            out = os.path.join(dest, name)
            os.makedirs(os.path.dirname(out), exist_ok=True)
            open(out, 'wb').write(vpk_read(e))
    shutil.rmtree(dest + '/_zip', ignore_errors=True)


def l4d1_classes():
    """Entity classes L4D1 knows: strings in server.so plus every class used by a stock map."""
    out = subprocess.run(['strings', L4D1_SERVER_SO], capture_output=True, text=True).stdout
    known = set(re.findall(r'^[a-z_0-9]+$', out, re.M))
    # LINK_ENTITY_TO_CLASS leaves a static named after the class (_ZL24prop_physics_multiplayer); the bare
    # string can be glued to a neighbour ("Dprop_physics_multiplayer") and missed by the line match above
    known |= {m[1][:int(m[0])] for m in re.findall(r'_ZL(\d+)([a-z_0-9]+)', out)}
    for b in glob.glob(os.path.dirname(os.path.dirname(L4D1_SERVER_SO)) + '/maps/l4d_*.bsp'):
        d = open(b, 'rb').read()
        known |= {kv.get('classname') for kv, _ in ents(d, lumps(d)[1])}
    return known


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('src')
    ap.add_argument('--name', help='output name (default: input file stem)')
    ap.add_argument('--drop-models', nargs='*', default=list(DEFAULT_DROP),
                    help=f'static prop model prefixes to remove (default: {" ".join(DEFAULT_DROP)})')
    ap.add_argument('--no-dict', action='store_true',
                    help='skip dictbuild.sh; the VPK then keeps L4D2 dictionaries and MUST NOT ship')
    ap.add_argument('--no-comp', action='store_true', help='skip porting Comp Rework stripper cfgs (compstripper.py)')
    ap.add_argument('--no-verify', action='store_true', help='skip loading the ported cfgs on the strip rig (stripverify.sh)')
    a = ap.parse_args()
    name = a.name or re.sub(r'[^a-z0-9_]+', '_', os.path.basename(a.src).rsplit('.', 1)[0].lower())
    work = os.path.join(HERE, 'out', name)
    src_dir, pkg = os.path.join(work, 'src'), os.path.join(work, 'pkg')
    # keep flow dumps (flowdump.sh output) across rebuilds; rerun flowdump.sh if the maps changed
    for sub in ('src', 'pkg', 'rotoblin'):
        shutil.rmtree(os.path.join(work, sub), ignore_errors=True)
    os.makedirs(pkg)
    extract(os.path.abspath(a.src), src_dir)
    have, l2 = indexes(os.path.join(HERE, 'out', '.index.pkl'))
    prefixes = tuple(a.drop_models)
    rep = []
    say = lambda s='': (rep.append(s), print(s))

    known = l4d1_classes() if os.path.exists(L4D1_SERVER_SO) else None
    handled = set(l4d2to1.DROP) | set(l4d2to1.RENAME) | {'weapon_spawn', 'weapon_item_spawn', 'weapon_gascan_spawn'}
    bsps = sorted(glob.glob(src_dir + '/maps/*.bsp'))
    if not bsps:
        sys.exit('no maps/*.bsp in the input')

    # ---- analysis ------------------------------------------------------------------------------
    say(f'== {name}: {len(bsps)} maps')
    vs = [p for p in glob.glob(src_dir + '/scripts/vscripts/**/*', recursive=True) if os.path.isfile(p)]
    if vs:
        say(f'!! {len(vs)} VScript files shipped (L4D1 has no VScript; their behaviour is LOST):')
        for p in vs:
            say('   ' + os.path.relpath(p, src_dir))
    need, drop, director_scripts = set(), set(), {}
    for b in bsps:
        d = open(b, 'rb').read(); ver, L = lumps(d)
        m = os.path.basename(b)[:-4]
        E = ents(d, L)
        pk = {p.lower() for p in pak(d, L)}
        script = [(kv.get('classname'), k, v[:80]) for kv, pairs in E for k, v in pairs
                  if k.lower() in ('vscripts', 'thinkfunction', 'scriptfile') and v
                  or re.search(r'runscript|callscriptfunction|beginscript|endscript', v, re.I)]
        # Director Scripts ("BeginScript c9m2_nobosses") are lost in L4D1; keep where they fire so
        # rotoblin.py can turn no-boss stretches into mapinfo ban windows.
        brushes = rotoblin.brush_centers(d, L)
        for kv, pairs in E:
            for k, v in pairs:
                parts = re.split(r'[,\x1b]', v)
                if k.lower().startswith('on') and len(parts) > 2 and parts[1].lower() in ('beginscript', 'endscript'):
                    p = rotoblin.position(kv, brushes)
                    if p:
                        director_scripts.setdefault(m.lower(), []).append(
                            (parts[1].lower()[:-6], parts[2], kv.get('targetname') or kv.get('classname'), p))
        unknown = collections.Counter(kv.get('classname') for kv, _ in E
                                      if known and kv.get('classname') not in known
                                      and kv.get('classname') not in handled)
        say(f'-- {m}: BSP v{ver}, {len(E)} entities')
        if any(kv.get('classname') == 'trigger_finale' for kv, _ in E):
            say('   has trigger_finale (check it is not a scripted L4D2 finale)')
        for c, k, v in script:
            say(f'   !! script hook: {c} {k} = {v}  (stripped)')
        for c, n in unknown.items():
            say(f'   !! {n}x {c}: not an L4D1 entity, the engine will ignore it')
        for t in texdata(d, L):
            v = f'materials/{t}.vmt'
            if v not in have and v not in pk:
                need.add(v)
        for p in staticprops(d, L)[1] + [kv.get('model', '').lower() for kv, _ in E]:
            if p.endswith('.mdl') and p not in have and p not in pk:
                if p.startswith(prefixes):
                    drop.add(p)  # only models players lack; stock L4D1/pack copies are safe
                else:
                    need.add(p)

    # ---- assets: pull anything players lack from the L4D2 install ----------------------------
    missing, copied, todo, seen = [], 0, sorted(need), set()
    while todo:
        f = todo.pop()
        if f in seen or f in have:
            continue
        seen.add(f)
        if os.path.exists(os.path.join(src_dir, f)):
            continue  # the campaign ships it
        if f not in l2:
            missing.append(f); continue
        data = vpk_read(l2[f])
        files = {f: data}
        if f.endswith('.mdl'):
            stem = f[:-4]
            files.update({k: vpk_read(e) for k, e in l2.items() if k.startswith(stem + '.')})
            ntex, tidx, ncd, cdidx = struct.unpack_from('<iiii', data, 204)
            texs = [data[tidx + 64 * i + struct.unpack_from('<i', data, tidx + 64 * i)[0]:].split(b'\0')[0]
                    for i in range(ntex)]
            cds = [data[struct.unpack_from('<i', data, cdidx + 4 * i)[0]:].split(b'\0')[0] for i in range(ncd)]
            for t in texs:
                for cd in cds:
                    v = ('materials/' + (cd.decode().strip('/\\') + '/' if cd.strip(b'/\\') else '')
                         + t.decode() + '.vmt').lower().replace('\\', '/')
                    if v in l2 or v in have:
                        todo.append(v); break
        elif f.endswith('.vmt'):
            for k, val in re.findall(r'"?(\$\w+|include)"?\s+"?([^"\s]+)"?', data.decode('latin1')):
                val = val.lower().replace('\\', '/')
                if k == 'include':
                    todo.append(val)
                elif '/' in val and not val.startswith('['):
                    todo.append('materials/' + val + ('' if val.endswith('.vtf') else '.vtf'))
        for k, b in files.items():
            if k in have:
                continue
            out = os.path.join(pkg, k); os.makedirs(os.path.dirname(out), exist_ok=True)
            open(out, 'wb').write(b); copied += 1
    say(f'== assets: {copied} files pulled from L4D2, {len(missing)} not found anywhere')
    for f in missing:
        say('   !! missing: ' + f)

    # ---- campaign's own files (minus Hammer leftovers) -------------------------------------------
    # sound/sound.cache is the game's own precache index; an addon copy replaces the player's for every map
    skip = re.compile(r'\.(vmf|vmx|log|prt|lin|jpg|bak)$|^maps/.*\.(vtf|bmp)$|^scripts/vscripts/|^sound/sound\.cache$', re.I)
    shadows = []
    for root, _, fs in os.walk(src_dir):
        for fn in fs:
            rel = os.path.relpath(os.path.join(root, fn), src_dir).replace('\\', '/').lower()
            if skip.search(rel) or rel.startswith('maps/') or not '/' in rel:
                continue
            if rel in have:
                shadows.append(rel)
            out = os.path.join(pkg, rel); os.makedirs(os.path.dirname(out), exist_ok=True)
            shutil.copy(os.path.join(root, fn), out)
    if shadows:  # kept (the author changed them on purpose), but they apply to every map while installed
        say(f'!! {len(shadows)} files replace ones players already have (stock or our pack), on every map:')
        for f in sorted(shadows):
            say('   ' + f)

    # ---- maps and navs ---------------------------------------------------------------------------
    os.makedirs(pkg + '/maps', exist_ok=True)
    for b in bsps:
        m = os.path.basename(b)[:-4].lower()
        log = l4d2to1.convert(b, f'{pkg}/maps/{m}.bsp', tuple(drop))
        say(f'-- converted {m}:')
        for k, n in sorted(log.items()):
            say(f'   {n:5d}  {k}')
        nav = b[:-4] + '.nav'
        if os.path.exists(nav):
            n, v = nav2to1.convert(nav, f'{pkg}/maps/{m}.nav')
            say(f'   nav: {n} areas, {v} visibility entries remapped')
        else:
            say('   !! no .nav shipped: the map is unplayable in versus without one')

    # ---- water L4D1 cannot draw: crashes the L4D1 client, gets an L4D1 copy under its own name (waterfix.py)
    # Judge each water by the copy the client actually loads: the campaign's, else our pack's, else the
    # L4D1 install's (left4dead_dlc3 before left4dead). Being in the install proves nothing:
    # left4dead_dlc3 ships L4D2-style water no stock map draws (liquids/water_c5m1_flow_beneath crashed
    # Detour Ahead 4 when it was skipped, 2026-10-17).
    client = {}
    for v in [f'{L4D1}/hl2/hl2_misc_dir.vpk', f'{L4D1}/left4dead/pak01_dir.vpk', f'{L4D1}/left4dead_dlc3/pak01_dir.vpk',
              *sorted(glob.glob(f'{L4D1}/left4dead/addons/*l4d2maps_*.vpk'))]:
        if os.path.exists(v):
            client.update({k: e for k, e in vpk_index(v).items() if k.endswith('.vmt')})

    def read_vmt(name):
        f = f'{pkg}/materials/{name}.vmt'
        if os.path.exists(f):
            return open(f, encoding='latin1').read()
        e = client.get(f'materials/{name}.vmt') or l2.get(f'materials/{name}.vmt')
        return vpk_read(e).decode('latin1') if e else None

    def write_vmt(name, text):
        f = f'{pkg}/materials/{name}.vmt'
        os.makedirs(os.path.dirname(f), exist_ok=True)
        open(f, 'w', encoding='latin1').write(text)

    have_tex = lambda t: (f'materials/{t.lower()}.vtf' in have
                          or os.path.exists(f'{pkg}/materials/{t.lower()}.vtf'))
    # Valve's own L4D1 water: in the base install, not overridden by our pack or the campaign. Everything
    # else that is expensive water gets made cheap (see waterfix.unsafe_water).
    base = set(vpk_index(f'{L4D1}/left4dead/pak01_dir.vpk')) if os.path.exists(f'{L4D1}/left4dead/pak01_dir.vpk') else set()
    packed = set()
    for v in glob.glob(f'{L4D1}/left4dead/addons/*l4d2maps_*.vpk') + [f'{L4D1}/left4dead_dlc3/pak01_dir.vpk']:
        if os.path.exists(v):
            packed |= {k for k in vpk_index(v) if k.endswith('.vmt')}
    stock = lambda n: (f'materials/{n}.vmt' in base and f'materials/{n}.vmt' not in packed
                       and not os.path.exists(f'{pkg}/materials/{n}.vmt'))
    waters = waterfix.fix(sorted(glob.glob(pkg + '/maps/*.bsp')), read_vmt, write_vmt, have_tex, say, stock)
    if waters:
        say(f'== {len(waters)} water materials L4D1 cannot draw rewritten: {", ".join(waters)}')

    # ---- mission files ---------------------------------------------------------------------------
    # Map names lower-cased to match the BSPs. L4D1 scores with a per-map "VersusModifier" (stock 1.0,
    # Dead Center finale 1.75) where L4D2 uses "VersusCompletionScore"; 400 points = 1.0. L4D1 boss
    # chances are fractions, L4D2 customs often write percentages ("75").
    for mf in glob.glob(pkg + '/missions/*.txt'):
        t = open(mf, encoding='latin1').read()
        t = re.sub(r'("Map"\s+")([^"]+)"', lambda mm: mm.group(1) + mm.group(2).lower() + '"', t, flags=re.I)
        n_mod = 0
        if not re.search(r'"VersusModifier"', t, re.I):
            def modifier(mm):
                nonlocal n_mod; n_mod += 1
                return f'{mm.group(1)}"VersusModifier"\t"{round(int(mm.group(2)) / 400, 2):g}"'
            t = re.sub(r'(\s*)"VersusCompletionScore"\s+"(\d+)"', modifier, t, flags=re.I)
        t = re.sub(r'("(?:tank|witch)_chance"\s+")(\d+(?:\.\d+)?)"',
                   lambda mm: mm.group(1) + (f'{float(mm.group(2)) / 100:g}' if float(mm.group(2)) > 1
                                             else mm.group(2)) + '"', t, flags=re.I)
        open(mf, 'w', encoding='latin1').write(t)
        say(f'== mission {os.path.basename(mf)}: map names lower-cased, {n_mod} VersusModifier from '
            f'VersusCompletionScore, boss chances as fractions')

    # ---- model meshes: L4D1 loads <model>.vtx, L4D2 ships <model>.dx90.vtx -----------------------
    # Without the plain name the model loads with no mesh ("MDLCache: Failed load of .VTX data") and the
    # client crashes drawing it (divide by zero in shaderapidx9.dll, Haunted Forest 2026-10-17).
    # The server never draws, so a server boot test does not catch this.
    n_vtx = 0
    for v in glob.glob(pkg + '/models/**/*.vtx', recursive=True):
        base, kind = re.match(r'(.*?)((?:\.(?:dx80|dx90|sw|xbox))?)\.vtx$', v).groups()
        if kind == '.dx90' and not os.path.exists(base + '.vtx'):
            os.rename(v, base + '.vtx')
            n_vtx += 1
        elif kind in ('.dx80', '.sw', '.xbox'):
            os.remove(v)  # mesh variants L4D1 never reads
    if n_vtx:
        say(f'== {n_vtx} models: .dx90.vtx renamed to .vtx (the name L4D1 loads)')

    # ---- pack (L4D1 only reads VPK v1) ---------------------------------------------------------
    if not os.path.exists(VENV):
        subprocess.run([sys.executable, '-m', 'venv', VENV], check=True)
        subprocess.run([VENV + '/bin/pip', '-q', 'install', 'vpk'], check=True)
    out = os.path.join(work, f'{name}_l4d1.vpk')
    subprocess.run([VENV + '/bin/python', '-c',
                    'import sys, vpk; p = vpk.new(sys.argv[1]); p.version = 1; p.save(sys.argv[2])', pkg, out],
                   check=True, cwd='/tmp')
    say(f'== wrote {out} ({os.path.getsize(out) // 2**20} MB)')
    json.dump(director_scripts, open(os.path.join(work, 'director_scripts.json'), 'w'), indent=1)
    say(f'== Rotoblin starter files: {rotoblin.main(pkg)} (see README "Rotoblin integration")')
    if not a.no_comp:
        try:
            for line in compstripper.main([name]):
                say('== Comp Rework stripper: ' + line + f' (report: out/{name}/rotoblin/compstripper.txt)')
        except subprocess.CalledProcessError as e:
            say(f'!! compstripper.py failed ({e}); maps keep the Rotoblin starter cfgs')
    # Last, because it loads the finished VPK on the Dallas mirror and repacks it (see dictbuild.sh).
    if a.no_dict:
        say('!! --no-dict: maps keep L4D2 string table dictionaries; run ./dictbuild.sh before shipping')
    else:
        r = subprocess.run([os.path.join(HERE, 'dictbuild.sh'), name], capture_output=True, text=True)
        say('== dictbuild.sh: ' + ' | '.join(l for l in r.stdout.splitlines() if 'srcds_run' not in l and 'Killed' not in l))
        if r.returncode:
            say(f'!! dictbuild.sh FAILED (exit {r.returncode}): this VPK MUST NOT ship until it succeeds\n{r.stderr[-2000:]}')
    # After dictbuild: it loads the final VPK, which then carries the dictionaries.
    v = None
    if not a.no_comp and not a.no_verify:
        v = subprocess.run([os.path.join(HERE, 'stripverify.sh'), name], capture_output=True, text=True)
        for line in v.stdout.splitlines():
            say('== stripverify.sh: ' + line)
        if v.returncode:
            say(f'!! stripverify.sh FAILED (exit {v.returncode}): fix the ported stripper cfgs before shipping them')
    open(os.path.join(work, 'report.txt'), 'w').write('\n'.join(rep) + '\n')
    if (not a.no_dict and r.returncode) or (v and v.returncode):
        sys.exit(1)


if __name__ == '__main__':
    main()
