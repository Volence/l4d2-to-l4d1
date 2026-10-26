#!/usr/bin/env python3
"""Write an L4D1 addoninfo.txt into a converted campaign's package.

    ./addoninfo.py <name> [<name> ...]     rewrite out/<name>/pkg/addoninfo.txt (repack the VPK yourself)

Without one, the L4D1 Addons menu shows the addon under the title of the last addon it could read (players saw a
run of "Undead Zone" entries, 2026-10-25). convert.py's file copy skips the port's own top-level addoninfo.txt,
and several of those are malformed anyway (Open Road's description never closes its quote, CCR has loose text
after the closing brace), so this writes a clean one from the original's fields: app 500, the mission's
DisplayTitle (else the addon title minus " - L4D2"), version, author and description, plus addonContent_Campaign 1.
"""
import glob, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
KEYS = ('addontitle', 'addonversion', 'addonauthor', 'addondescription', 'addontagline')


def fields(text):
    """The original's values, read one key per line so a broken quote or brace cannot swallow the rest."""
    out = {}
    for line in text.splitlines():
        line = re.sub(r'\s//.*$', '', line).strip()
        m = re.match(r'"?([A-Za-z0-9_]+)"?\s+"?([^"]*)"?', line)
        if m and m.group(1).lower() in KEYS and m.group(1).lower() not in out:
            out[m.group(1).lower()] = m.group(2).strip()
    return out


def mission_title(pkg):
    """The first DisplayTitle in the package's mission files (CCR's addon title is "Crash Course but 5 Chapters")."""
    for mf in sorted(glob.glob(os.path.join(pkg, 'missions', '*.txt'))):
        for line in open(mf, encoding='latin1'):
            m = re.match(r'\s*"DisplayTitle"\s+"([^"]+)"', line, re.I)
            if m and not m.group(1).startswith('$'):  # Detour Ahead's is a localisation token
                return m.group(1).strip()
    return None


def render(f, name, title=None):
    title = title or re.sub(r'\s*-\s*L4D2$', '', f.get('addontitle') or name, flags=re.I)
    q = lambda s: s.replace('"', "'")
    lines = ['"AddonInfo"', '{',
             '\taddonSteamAppID\t\t500',
             f'\taddontitle\t\t"{q(title)}"',
             f'\taddonversion\t\t"{q(f.get("addonversion") or "1")}"']
    if f.get('addontagline'):
        lines.append(f'\taddontagline\t\t"{q(f["addontagline"])}"')
    if f.get('addonauthor'):
        lines.append(f'\taddonauthor\t\t"{q(f["addonauthor"])}"')
    lines += ['\taddonContent_Campaign\t1',
              f'\taddonDescription\t"{q(f.get("addondescription") or title)} (L4D1 conversion)"',
              '}', '']
    return '\n'.join(lines)


def write(src_dir, pkg, name):
    """Write pkg/addoninfo.txt; returns the title used."""
    p = os.path.join(src_dir, 'addoninfo.txt')
    f = fields(open(p, encoding='latin1').read()) if os.path.exists(p) else {}
    text = render(f, name, mission_title(pkg))
    open(os.path.join(pkg, 'addoninfo.txt'), 'w', encoding='latin1').write(text)
    return re.search(r'addontitle\t\t"([^"]*)"', text).group(1)


if __name__ == '__main__':
    for n in sys.argv[1:]:
        work = os.path.join(HERE, 'out', n)
        print(n, '->', write(os.path.join(work, 'src'), os.path.join(work, 'pkg'), n))
