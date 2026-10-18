"""Give L4D2 flow-map water an L4D1-drawable copy under its own name.

L4D2 water materials with $flowmap make L4D1's Water shader come up with no vertex format, and the client
dies with a divide by zero in shaderapidx9.dll the moment it draws the surface (Haunted Forest
liquids/water_swamp_m2_beneath, found by bisecting world materials in the client 2026-10-17). The server
never draws, so a server boot test passes.

The fixed copy cannot reuse the original path: our 00_l4d2maps_* pack ships L4D2's version of many of these
materials and sorts ahead of a campaign VPK, so it would win. Each one becomes materials/l4d1/<path>.vmt and
the map's texture names, its cubemap patch materials and any $bottommaterial pointing at it are repointed.
"""
import io, re, struct, zipfile

PREFIX = 'l4d1/'
SHADER = re.compile(r'\s*(?://[^\n]*\n\s*)*"?([A-Za-z0-9_]+)"?')
KEEP = ('$abovewater', '$bottommaterial', '$fogenable', '$fogcolor', '$fogstart', '$fogend', '$lightmapwaterfog',
        '$surfaceprop', '%compilewater', '%tooltexture', '$normalmap', '$reflecttint', '$refracttint',
        '$refractamount', '$reflectamount', '$envmaptint', '$scale', '$flashlighttint')


def is_flow_water(text):
    m = SHADER.match(text)
    return bool(m) and m.group(1).lower() == 'water' and re.search(r'\$flowmap\b', text, re.I) is not None


def l4d1_water(text, have_texture):
    """Cheap L4D1 water from an L4D2 flow-map water: keep fog, normals and surface; drop the flow keys."""
    out = ['Water', '{', '$forcecheap 1', '$envmap env_cubemap', '$bumpframe 0']
    for k, v in re.findall(r'^\s*"?([$%][A-Za-z0-9_]+)"?\s+(.+?)\s*$', text, re.M):
        kl = k.lower()
        if kl not in KEEP:
            continue
        val = v.strip().strip('"')
        if kl == '$normalmap' and not have_texture(val):
            val = 'nature/water_frame01_normal'
        if kl == '$bottommaterial':
            val = PREFIX + val.replace('\\', '/').lower()  # repointed; the bottom is converted too
        out.append(f'{k} "{val}"')
    if not any(l.lower().startswith('$normalmap') for l in out):
        out.append('$normalmap "nature/water_frame01_normal"')
    out.append('$bumpmap "nature/water_frame01_dudv"')
    return '\n'.join(out + ['}', ''])


def _lumps(d):
    return [list(struct.unpack('<iiii', d[8 + 16 * i:24 + 16 * i])) for i in range(64)]  # v20: ofs len ver cc


def replace_lumps(path, new):
    """Rewrite a v20 BSP with some lumps replaced, relaying out everything after them (game lump fixed up)."""
    d = open(path, 'rb').read()
    L = _lumps(d)
    data = {i: d[o:o + n] for i, (o, n, v, c) in enumerate(L)}
    data.update(new)
    go = L[35][0]
    ng = struct.unpack('<i', d[go:go + 4])[0]
    heads = [list(struct.unpack('<iHHii', d[go + 4 + 16 * i:go + 20 + 16 * i])) for i in range(ng)]
    bodies = [d[h[3]:h[3] + h[4]] for h in heads]
    out = bytearray(1036)
    for i in sorted(range(64), key=lambda i: L[i][0]):
        while len(out) % 4:
            out += b'\0'
        if i == 35:
            pos = len(out) + 4 + 16 * ng
            blob = struct.pack('<i', ng)
            for h, b in zip(heads, bodies):
                blob += struct.pack('<iHHii', h[0], h[1], h[2], pos, len(b))
                pos += len(b)
            blob += b''.join(bodies)
        else:
            blob = data[i]
        L[i][0], L[i][1] = (len(out), len(blob)) if blob else (0, 0)
        out += blob
    out[0:8] = d[0:8]
    for i in range(64):
        out[8 + 16 * i:24 + 16 * i] = struct.pack('<iiii', *L[i])
    out[1032:1036] = d[1032:1036]
    open(path, 'wb').write(out)


def texture_names(d):
    L = _lumps(d)
    s = d[L[43][0]:L[43][0] + L[43][1]]
    offs = struct.unpack(f'<{L[44][1] // 4}i', d[L[44][0]:L[44][0] + L[44][1]])
    return s, offs


def pak_files(d):
    L = _lumps(d)
    z = zipfile.ZipFile(io.BytesIO(d[L[40][0]:L[40][0] + L[40][1]]))
    return {n: z.read(n) for n in z.namelist()}


def fix(bsp_paths, read_vmt, write_vmt, have_texture, say):
    """read_vmt(path under materials/, no ext) -> text or None; write_vmt(path, text) adds it to the package."""
    norm = lambda n: n.replace('\\', '/').lower().removesuffix('.vmt').removeprefix('materials/')
    fixed = {}

    def convert(name):
        name = norm(name)
        if name in fixed:
            return fixed[name]
        text = read_vmt(name)
        if text is None or not is_flow_water(text):
            fixed[name] = None
            return None
        fixed[name] = PREFIX + name
        write_vmt(PREFIX + name, l4d1_water(text, have_texture))
        b = re.search(r'\$bottommaterial"?\s+"?([^"\s]+)', text, re.I)
        if b and convert(b.group(1)) is None:  # bottom is fine as it is: point back at the original
            fixed_text = l4d1_water(text, have_texture).replace(PREFIX + norm(b.group(1)), norm(b.group(1)))
            write_vmt(PREFIX + name, fixed_text)
        return fixed[name]

    for path in bsp_paths:
        d = open(path, 'rb').read()
        new = {}
        s, offs = texture_names(d)
        names = [s[x:s.index(b'\0', x)].decode('latin1') for x in offs]
        pak = pak_files(d)
        # cubemap patch materials in the pak include the water by its full path
        pak_new, n_patch = {}, 0
        for fn, raw in pak.items():
            if not fn.lower().endswith('.vmt'):
                continue
            t = raw.decode('latin1')
            m = re.search(r'("?include"?\s+")([^"]+)(")', t, re.I)
            if m and convert(m.group(2)):
                t = t[:m.start(2)] + 'materials/' + fixed[norm(m.group(2))] + '.vmt' + t[m.end(2):]
                pak_new[fn] = t.encode('latin1')
                n_patch += 1
        n_tex = 0
        for i, nm in enumerate(names):
            if convert(nm):
                names[i] = fixed[norm(nm)]
                n_tex += 1
        if n_tex:
            blob, offs2 = bytearray(), []
            for nm in names:
                offs2.append(len(blob))
                blob += nm.encode('latin1') + b'\0'
            new[43], new[44] = bytes(blob), struct.pack(f'<{len(offs2)}i', *offs2)
        if pak_new:
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, 'w', zipfile.ZIP_STORED) as z:  # BSP paks must stay uncompressed
                for fn, raw in pak.items():
                    z.writestr(fn, pak_new.get(fn, raw))
            new[40] = buf.getvalue()
        if new:
            replace_lumps(path, new)
            say(f'   {path.rsplit("/", 1)[-1]}: {n_tex} water surfaces + {n_patch} cubemap patches -> L4D1 water')
    return sorted(k for k, v in fixed.items() if v)
