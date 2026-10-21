#!/usr/bin/env python3
"""Port an L4D2 Stripper:Source map config (SirPlease L4D2-Competitive-Rework, zonemod) to our L4D1 conversion.

    stripper2to1.py <l4d2 cfg> <original L4D2 bsp> <converted L4D1 bsp> <out cfg> [--report file]

Every filter/modify match is run against the entity lumps of both BSPs. A match that found entities in L4D2
but finds none in the converted map is reported (the converter renamed or dropped them). Entities the config
adds go through the converter's own convert_entity(), plus the rules L4D1 needs on top:

- env_physics_blocker does not exist in L4D1; env_player_blocker is its L4D1 ancestor (mins/maxs, BlockType
  0 everyone / 1 survivors / 2 player infected). L4D2 BlockType 4 (players and physics objects) keeps only
  its player half (0): no L4D1 player blocker stops props. boxmins/boxmaxs (L4D2's oriented box) become
  mins/maxs; a rotated box is left with its angles for deploy/tools/blocker-angles to split, because L4D1
  ignores angles on a player blocker.
- L4D2-only classes (point_nav_attribute_region, script_nav_blocker, script_clip_vphysics, logic_script) are
  commented out with a note.
- Outputs: ESC separators become commas, ForcePanicEvent becomes PanicEvent, VScript outputs go.
"""
import re, sys, os, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bspinfo
from l4d2to1 import convert_entity, L2_INPUTS, L2_OUTPUT_HINT

NO_L4D1_CLASS = {'point_nav_attribute_region', 'script_nav_attribute_region', 'script_nav_blocker',
                 'script_clip_vphysics', 'logic_script', 'info_ladder_dismount_l4d2'}
# infected class numbers: L4D2 1 smoker 2 boomer 3 hunter 4 spitter 5 jockey 6 charger 7 witch 8 tank;
# L4D1 1 smoker 2 boomer 3 hunter 4 witch 5 tank.
INFECTED_CLASS = {'7': '4', '8': '5'}
# Inputs these configs call that L4D1's server.so does not have (checked against its strings 2026-10-21).
# L4D1 cannot ignore fall damage at all, so the comp ladder fall-damage triggers have no port.
L2_ONLY_INPUTS = {'ignorefalldamagewithoutreset', 'ignorefalldamage', 'gauntletstoppanic', 'endcustomscriptedstage',
                  'howangry', 'endscript', 'beginscript'}


class Ent(dict):
    """First value of each key (lowercased), plus .pairs with every (key, value): outputs repeat keys."""
    def __init__(self, pairs):
        self.pairs = [(k.lower(), v.replace('\x1b', ',')) for k, v in pairs]
        super().__init__(reversed(self.pairs))


def load_ents(bsp):
    d = open(bsp, 'rb').read()
    _, L = bspinfo.lumps(d)
    return [Ent(pairs) for _, pairs in bspinfo.ents(d, L)]


def value_match(want, have):
    if have is None:
        return False
    if len(want) > 1 and want.startswith('/') and want.endswith('/'):
        return re.search(want[1:-1], have) is not None
    return want == have


def match_count(ents, pairs):
    """Stripper semantics: an entity matches when every listed key matches one of its values."""
    n = 0
    for e in ents:
        ok = True
        for k, v in pairs:
            haves = [b for a, b in e.pairs if a == k.lower()]
            if k.lower().startswith('on'):  # output: compare without separators
                haves = [h.replace(',', '') for h in haves]
                v = v.replace('\x1b', '').replace(',', '')
            if not any(value_match(v, h) for h in haves):
                ok = False
                break
        n += ok
    return n


def matches(ents, pairs):
    return [e for e in ents if match_count([e], pairs)]


def by_hammerid(hits):
    hids = [e.get('hammerid') for e in hits]
    if not hids or not all(hids):
        return None
    return ('hammerid', hids[0] if len(hids) == 1 else '/^(' + '|'.join(hids) + ')$/')


def translate_output(k, v):
    """(key, value) or None for a modify action's output; value ESC- or comma-separated."""
    v = v.replace('\x1b', ',')
    if not (k.lower().startswith('on') or k.lower() == 'outvalue'):
        return k, v
    if L2_OUTPUT_HINT.search(v):
        return None
    p = v.split(',')
    if len(p) > 1 and p[1].lower() in L2_INPUTS:
        p[1] = L2_INPUTS[p[1].lower()]
    if len(p) > 1 and p[1].lower() in L2_ONLY_INPUTS:
        return None
    return k, ','.join(p)


def apply_actions(e, acts):
    """Apply modify actions to an L4D2 entity (dict, lowercased keys) and return the new ordered pairs."""
    pairs = list(e.pairs)
    for s_, k, v in acts:
        kl = k.lower()
        if s_ == 'replace':
            pairs = [(a, v if a == kl else b) for a, b in pairs]
        elif s_ == 'insert':
            pairs.append((kl, v))
        elif s_ == 'delete':
            pairs = [(a, b) for a, b in pairs if not (a == kl and b.replace('\x1b', ',') == v.replace('\x1b', ','))]
    return pairs


def port_modify(match, acts, hits2, n1, dst_ents):
    """Port one modify block. Returns (new lines, 'same' to keep it as written, or None to comment it out; note)."""
    l2 = [a for a in acts if a[1].lower() in ('weapon_selection', 'spawn_without_director', 'melee_weapon', 'glowrange')
          or re.fullmatch(r'item\d+', a[1], re.I)]
    outs, note, changed = [], [], bool(l2)
    for s_, k, v in acts:
        if (s_, k, v) in l2:
            continue
        t = translate_output(k, v)
        if t is None:
            note.append(f'dropped {s_} {k} "{v.replace(chr(27), ",")}" (VScript or an input L4D1 does not have)')
            changed = True
            continue
        changed |= t[1] != v
        outs.append((s_,) + t)
    if not hits2:
        note.insert(0, 'matches nothing in L4D2 either')
        return ('same' if not changed else None), '; '.join(note)
    rekey = n1 != len(hits2)
    if not changed and not rekey:
        return 'same', ''
    key = by_hammerid(hits2)
    if (rekey or l2) and key is None:
        return None, 'MANUAL: no hammerids on the L4D2 matches; ' + '; '.join(note)
    lines, filt = [], []
    if not l2:
        lines = port_block(key if rekey else None, [], outs, match)
        if rekey:
            note.append('matched by hammerid (the converter renamed the original match)')
    else:
        # The converter already turned these into L4D1 classes. Apply the change to the L4D2 entity and convert
        # it again (same pick), then make the converted entity that class.
        dst_by_hid = {e.get('hammerid'): e for e in dst_ents if e.get('hammerid')}
        groups = collections.OrderedDict()
        for e in hits2:
            conv = convert_entity(apply_actions(e, l2), collections.Counter())
            want = None if conv is None else (dict(conv)['classname'], dict(conv).get('model'))
            cur = dst_by_hid.get(e['hammerid'])
            groups.setdefault((want, cur and (cur.get('classname'), cur.get('model'))), []).append(e)
        for (want, cur), es in groups.items():
            hk = by_hammerid(es)
            if want is None:
                filt.append(hk)
                note.append(f'{len(es)} have no L4D1 item left: filtered')
                continue
            rep, extra = [('classname', want[0])], []
            if want[1] and (not cur or cur[1] != want[1]):
                if cur and cur[1]:
                    rep.append(('model', want[1]))
                else:  # Stripper's replace only changes a key that exists; an item spawn has no model key
                    extra.append(('insert', 'model', want[1]))
            if cur and cur[0] == want[0] and len(rep) == 1 and not extra:
                rep = []
                note.append(f'{len(es)} already {want[0]} in the conversion')
            else:
                note.append(f'{len(es)} -> {want[0]}')
            lines += port_block(hk, rep, extra + outs)
    if not lines and not filt:
        return None, '; '.join(note) or 'nothing left to change in L4D1'
    if filt:  # switch to filter: for these, then back to modify: for whatever follows in the cfg
        lines = ['filter:'] + [l for hk in filt for l in fmt_block([hk])] + ['modify:'] + lines
    return lines, '; '.join(note)


def port_block(key, replace, outs, match=None):
    L = ['{', '\tmatch:', '\t{']
    L += [f'\t\t"{k}" "{v}"' for k, v in ([key] if key else match)]
    L.append('\t}')
    secs = collections.OrderedDict()
    if replace:
        secs['replace'] = list(replace)
    for s_, k, v in outs:
        secs.setdefault(s_, []).append((k, v))
    if not secs:
        return []
    for s_, kv in secs.items():
        L += [f'\t{s_}:', '\t{'] + [f'\t\t"{k}" "{v}"' for k, v in kv] + ['\t}']
    return L + ['}']


# ---------------------------------------------------------------- parsing
TOKEN = re.compile(r'"((?:[^"\\]|\\.)*)"\s+"((?:[^"\\]|\\.)*)"')


def parse(text):
    """Split into a flat list of items: ('raw', line) for comments/blank/section words, ('block', lines) for {...}.
    Nested match:/replace:/insert:/delete: blocks inside a modify block stay inside the block's lines."""
    out, cur, depth = [], None, 0
    for line in text.split('\n'):
        s = line.strip()
        if cur is None:
            if s.startswith('{'):
                cur, depth = [line], s.count('{') - s.count('}')
                if depth == 0:
                    out.append(('block', cur)); cur = None
            else:
                out.append(('raw', line))
        else:
            cur.append(line)
            if not s.startswith(';'):
                depth += s.count('{') - s.count('}')
            if depth <= 0:
                out.append(('block', cur)); cur = None
    if cur:
        out.append(('block', cur))
    return out


def block_pairs(lines):
    """Ordered (section, key, value, line index) for a block; section '' for a flat block."""
    sec, res = '', []
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith(';'):
            continue
        m = re.match(r'(match|replace|insert|delete)\s*:', s, re.I)
        if m:
            sec = m.group(1).lower()
            continue
        for k, v in TOKEN.findall(line.split(';')[0] if not line.strip().startswith('"') else line):
            res.append((sec, k, v, i))
    return res


# ---------------------------------------------------------------- translation
def fix_outputs(pairs, notes):
    out = []
    for k, v in pairs:
        if k.lower().startswith('on') or k.lower() == 'outvalue':
            v = v.replace('\x1b', ',')
            p = v.split(',')
            if len(p) > 1 and p[1].lower() in L2_INPUTS:
                notes.append(f'input {p[1]} -> {L2_INPUTS[p[1].lower()]}')
                p[1] = L2_INPUTS[p[1].lower()]
                v = ','.join(p)
            if L2_OUTPUT_HINT.search(v) or (len(p) > 1 and p[1].lower() in L2_ONLY_INPUTS):
                notes.append(f'dropped output {k} "{v}" (VScript or an input L4D1 does not have)')
                continue
        out.append((k, v))
    return out


def translate_add(pairs, notes):
    """pairs: [(key, value)] of an added entity. Returns new pairs, or None to comment the entity out."""
    kv = {k.lower(): v for k, v in pairs}
    cls = kv.get('classname', '')
    if cls in NO_L4D1_CLASS:
        notes.append(f'{cls} has no L4D1 class: left out')
        return None
    if cls == 'env_physics_blocker':
        bt = kv.get('blocktype', '0')
        new = []
        has_box = 'boxmins' in kv and 'boxmaxs' in kv
        for k, v in pairs:
            kl = k.lower()
            if kl == 'classname':
                v = 'env_player_blocker'
            elif kl == 'blocktype' and v in ('3', '4'):
                notes.append(f'BlockType {v} -> {"2" if v == "3" else "0"}'
                             + (' (L4D1 blockers never stop physics props)' if v == '4' else ''))
                v = '2' if v == '3' else '0'
            elif kl in ('mins', 'maxs') and has_box:
                continue  # L4D2 sizes the oriented box from boxmins/boxmaxs; TLS writes both, nearly always equal
            elif kl in ('boxmins', 'boxmaxs'):
                k = kl[3:]
            new.append((k, v))
        ang = [float(x) for x in kv.get('angles', '0 0 0').split()] if kv.get('angles') else [0, 0, 0]
        if any(abs(a) % 360 > 0.01 for a in ang):
            notes.append(f'rotated blocker (angles {kv["angles"]}): split by blocker-angles')
        return new
    if cls == 'filter_activator_infected_class':
        new = []
        for k, v in pairs:
            if k.lower() == 'filterinfectedclass':
                if v in ('4', '5', '6'):
                    notes.append(f'filterinfectedclass {v} is an L4D2-only class: never matches in L4D1')
                elif v in INFECTED_CLASS:
                    notes.append(f'filterinfectedclass {v} -> {INFECTED_CLASS[v]}')
                    v = INFECTED_CLASS[v]
            new.append((k, v))
        pairs = new
    log = collections.Counter()
    conv = convert_entity(list(pairs), log)
    for k, n in log.items():
        notes.append(k)
    if conv is None:
        return None
    had = any(k.lower().startswith('on') for k, _ in pairs)
    conv = fix_outputs(conv, notes)
    if had and not any(k.lower().startswith('on') for k, _ in conv) and cls.startswith(('trigger_', 'logic_')):
        notes.append(f'{cls} has no outputs left in L4D1: left out')
        return None
    return conv


def fmt_block(pairs, indent='\t'):
    return ['{'] + [f'{indent}"{k}" "{v}"' for k, v in pairs] + ['}']


def comment_out(lines):
    return [';' + l.replace('\x1b', ',') if l.strip() else l for l in lines]


# ---------------------------------------------------------------- driver
def port(cfg_text, src_ents, dst_ents, models_ok):
    items = parse(cfg_text)
    out, report, section = [], [], None
    stats = collections.Counter()
    for kind, x in items:
        if kind == 'raw':
            s = x.strip().lower()
            if s in ('filter:', 'add:', 'modify:', 'remove:'):
                section = 'filter' if s == 'remove:' else s[:-1]
            out.append(x)
            continue
        lines = x
        pairs = block_pairs(lines)
        notes = []
        first = next((l for l in lines if l.strip() and not l.strip().startswith('{')), '')
        label = f'{section} ' + ' '.join(f'{k}={v}' for s_, k, v, _ in pairs if k.lower() in
                                          ('classname', 'hammerid', 'targetname', 'origin', 'model'))[:160]
        if section == 'filter':
            flat = [(k, v) for _, k, v, _ in pairs]
            hits2, n1 = matches(src_ents, flat), match_count(dst_ents, flat)
            stats['filter'] += 1
            if n1 == len(hits2):
                out += lines
                continue
            m = by_hammerid(hits2)
            if m is None:
                report.append(f'FILTER L4D2 {len(hits2)} vs L4D1 {n1}, MANUAL (no hammerids): {label}')
                out += [f'; [L4D1] MANUAL: matches {len(hits2)} in L4D2, {n1} in L4D1'] + lines
                continue
            report.append(f'FILTER L4D2 {len(hits2)} vs L4D1 {n1}: rewritten by hammerid: {label}')
            out += [f'; [L4D1] the converter renamed these ({len(hits2)} L4D2 entities, {n1} L4D1 matches by the'
                    ' original keys): matched by hammerid instead'] + comment_out(lines) + fmt_block([m])
            continue
        if section == 'modify':
            m = [(k, v) for s_, k, v, _ in pairs if s_ == 'match']
            acts = [(s_, k, v) for s_, k, v, _ in pairs if s_ != 'match']
            hits2, n1 = matches(src_ents, m), match_count(dst_ents, m)
            stats['modify'] += 1
            block_out, rep = port_modify(m, acts, hits2, n1, dst_ents)
            rep = rep or 'outputs rewritten for L4D1 (comma separators, L4D1 input names)'
            if block_out != 'same':
                report.append(f'MODIFY L4D2 {len(hits2)} vs L4D1 {n1}: {label}: {rep}')
            if block_out is None:
                out += [f'; [L4D1] {rep}'] + comment_out(lines)
            elif block_out == 'same':
                out += [l.replace('\x1b', ',') for l in lines]
            else:
                out += [f'; [L4D1] {rep}'] + comment_out(lines) + block_out
            continue
        # add
        flat = [(k, v) for _, k, v, _ in pairs]
        stats['add'] += 1
        new = translate_add(flat, notes)
        if new is not None:
            model = dict((k.lower(), v) for k, v in new).get('model', '')
            if model and not model.startswith('*') and not models_ok(model):
                notes.append(f'model {model} not found in any L4D1/pack/campaign VPK: left out')
                new = None
        keep_comments = [l for l in lines if l.strip().startswith(';')]
        if new is None:
            report.append(f'ADD left out: {label} ({"; ".join(notes)})')
            out += [f'; [L4D1] {n}' for n in notes] + comment_out(lines)
            stats['add left out'] += 1
            continue
        if notes:
            report.append(f'ADD changed: {label} ({"; ".join(notes)})')
        out += [f'; [L4D1] {n}' for n in notes] + ['{'] + [f'\t{l.strip()}' for l in keep_comments] + \
               [f'\t"{k}" "{v}"' for k, v in new] + ['}']
    return '\n'.join(out), report, stats


def model_index(paths):
    import vpkread
    have = set()
    for p in paths:
        if p.endswith('.vpk') and os.path.exists(p):
            f, _, ents = vpkread.entries(p)
            have |= {e[0].lower() for e in ents}
        elif os.path.isdir(p):
            for root, _, files in os.walk(p):
                for fn in files:
                    have.add(os.path.relpath(os.path.join(root, fn), p).lower().replace(os.sep, '/'))
    return have


if __name__ == '__main__':
    a = [x for x in sys.argv[1:] if not x.startswith('--')]
    cfg, src, dst, outp = a[:4]
    extra = a[4:]
    have = model_index(extra)
    ok = lambda m: m.lower() in have
    text = open(cfg, encoding='latin1').read()
    res, rep, st = port(text, load_ents(src), load_ents(dst), ok)
    open(outp, 'w', encoding='latin1').write(res)
    print(os.path.basename(cfg), dict(st))
    for r in rep:
        print('  ', r)
