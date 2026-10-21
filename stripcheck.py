#!/usr/bin/env python3
"""Check a Stripper cfg against the entity lump the server actually spawned (stripper_dump output).

    stripcheck.py <cfg> <dump.cfg>

add:    each active entity is in the dump (same classname + origin, and mins/maxs for blockers)
filter: nothing in the dump matches
modify: every dump entity matching the match keys has the replace/insert values and none of the delete ones
Not problems (upstream does these on purpose or they are no-ops in L4D2 too): an add that a later filter removes,
a filter whose match a later add puts back, a replace of a key the entity does not have (Stripper only replaces
existing keys), a delete of a key the same block inserts again.
Prints only problems, then one summary line; exits 1 if there were any.
"""
import re, sys, collections
from stripper2to1 import parse, block_pairs, Ent, match_count, TOKEN


def dump_ents(path):
    text = open(path, encoding='latin1').read()
    return [Ent(TOKEN.findall(b)) for b in re.findall(r'\{(.*?)\}', text, re.S)]


def norm_vec(v):
    try:
        return tuple(round(float(x), 1) for x in v.replace(',', ' ').split())
    except ValueError:
        return v


def main(cfg, dump):
    ents = dump_ents(dump)
    have = collections.Counter((e.get('classname'), norm_vec(e.get('origin', '')), norm_vec(e.get('mins', '')))
                               for e in ents)
    items = parse(open(cfg, encoding='latin1').read())
    filters, adds, section = [], [], None
    for kind, x in items:
        if kind == 'raw' and x.strip().lower() in ('filter:', 'add:', 'modify:', 'remove:'):
            section = x.strip().lower()[:-1]
        elif kind == 'block' and section in ('filter', 'remove'):
            filters.append([(k, v) for _, k, v, _ in block_pairs(x)])
        elif kind == 'block' and section == 'add' and block_pairs(x):
            adds.append(Ent([(k, v) for _, k, v, _ in block_pairs(x)]))
    section, bad, n = None, [], collections.Counter()
    for kind, x in items:
        if kind == 'raw':
            s = x.strip().lower()
            if s in ('filter:', 'add:', 'modify:', 'remove:'):
                section = 'filter' if s == 'remove:' else s[:-1]
            continue
        pairs = block_pairs(x)
        if not pairs:
            continue
        n[section] += 1
        if section == 'add':
            kv = {k.lower(): v for _, k, v, _ in pairs}
            key = (kv.get('classname'), norm_vec(kv.get('origin', '')), norm_vec(kv.get('mins', '')))
            if have[key] <= 0:
                added = Ent([(k, v) for _, k, v, _ in pairs])
                if not any(f and match_count([added], f) for f in filters):
                    bad.append(f'ADD missing: {key}')
            else:
                have[key] -= 1
        elif section == 'filter':
            flat = [(k, v) for _, k, v, _ in pairs]
            c = match_count(ents, flat) - match_count(adds, flat)
            if c > 0:
                bad.append(f'FILTER still matches {c}: {flat}')
        elif section == 'modify':
            m = [(k, v) for s, k, v, _ in pairs if s == 'match']
            hits = [e for e in ents if match_count([e], m)]
            for e in hits:
                for s, k, v, _ in pairs:
                    vals = [b for a, b in e.pairs if a == k.lower()]
                    if s == 'replace' and not vals:
                        continue
                    if s == 'delete' and any(s2 == 'insert' and k2.lower() == k.lower() and v2 == v
                                             for s2, k2, v2, _ in pairs):
                        continue
                    if s in ('replace', 'insert') and v not in vals:
                        bad.append(f'MODIFY {m}: {s} {k}={v} not applied (has {vals[:3]})')
                    if s == 'delete' and v in vals:
                        bad.append(f'MODIFY {m}: delete {k}={v} still there')
    for b in bad:
        print('  ', b)
    print(f'{cfg.split("/")[-1]}: {len(ents)} entities in dump; checked {dict(n)}; {len(bad)} problems')
    return not bad


if __name__ == '__main__':
    sys.exit(0 if main(*sys.argv[1:3]) else 1)
