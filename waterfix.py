"""Give L4D2 water that L4D1 cannot draw an L4D1-drawable copy under its own name.

Some L4D2 Water materials make L4D1's Water shader come up with no vertex format, and the client dies with a
divide by zero in shaderapidx9.dll (+0x7561, GetMaxVerticesToRender) the moment it draws the surface. The
server never draws, so a server boot test passes. Found by bisecting world materials in the client
(clienttest/bisect.py), 2026-10-17:
  - liquids/water_swamp_m2_beneath (Haunted Forest 1): flow map, underwater, no reflect/refract texture
  - diescraper/pool_water_beneath (Diescraper 4): plain "$refract 1" underwater, no reflect/refract texture
Stock L4D1 water always names $refracttexture/$reflecttexture or runs $forcecheap, so a water that does
neither (or uses an L4D2 flow map) is rewritten as cheap L4D1 water. A water whose $bottommaterial gets
rewritten is copied too, so it points at the fixed bottom.

The fixed copy cannot reuse the original path: our 00_l4d2maps_* pack ships L4D2's version of many of these
materials and sorts ahead of a campaign VPK, so it would win. Each one becomes materials/l4d1/<path>.vmt and
the map's texture names, its cubemap patch materials and any $bottommaterial pointing at it are repointed.
"""
import io, re, struct, zipfile

PREFIX = 'l4d1/'
SHADER = re.compile(r'\s*(?://[^\n]*\n\s*)*"?([A-Za-z0-9_]+)"?')
# Only what Valve's own cheap water (liquids/ruralwater_river) uses. L4D2's $refracttint/$reflecttint are
# applied as a flat full-bright colour by L4D1's cheap path: Haunted Forest's swamp came out solid yellow.
KEEP = ('$abovewater', '$bottommaterial', '$fogenable', '$fogcolor', '$fogstart', '$fogend', '$lightmapwaterfog',
        '$surfaceprop', '%compilewater', '%tooltexture', '$normalmap', '$scale')
LIGHTMAP_FOG = re.compile(r'^\s*"?\$lightmapwaterfog"?\s+"?1', re.M | re.I)
LIGHTMAP_FOG_SCALE = 0.2


def is_water(text):
    m = SHADER.match(text)
    return bool(m) and m.group(1).lower() == 'water'


def unsafe_water(text):
    """True for water L4D1 cannot draw: an L4D2 flow map, or no reflect/refract texture and not cheap."""
    if not is_water(text):
        return False
    has = lambda k: re.search(r'"?' + re.escape(k) + r'"?\s', text, re.I) is not None
    return has('$flowmap') or not (has('$forcecheap') or has('$reflecttexture') or has('$refracttexture'))


def l4d1_water(text, have_texture):
    """Cheap L4D1 water from an L4D2 flow-map water: keep fog, normals and surface; drop the flow keys."""
    out = ['Water', '{', '$forcecheap 1', '$envmap env_cubemap', '$envmaptint "[1 1 1]"', '$envmapcontrast 1',
           '$reflectentities 0', '$bumpframe 0']
    for k, v in re.findall(r'^\s*"?([$%][A-Za-z0-9_]+)"?\s+(.+?)\s*$', text, re.M):
        kl = k.lower()
        if kl not in KEEP:
            continue
        val = v.strip().strip('"')
        if kl == '$normalmap' and not have_texture(val):
            val = 'nature/water_frame01_normal'
        if kl == '$bottommaterial':
            val = val.replace('\\', '/').lower()
            val = val if val.startswith(PREFIX) else PREFIX + val  # repointed; the bottom is converted too
        if kl == '$fogcolor' and LIGHTMAP_FOG.search(text):
            # L4D2 multiplies lightmapped water fog by the lightmap; L4D1 draws the fog unlit, so Detour
            # Ahead's dark sewer (fog 90 70 20) showed as a flat bright yellow sheet. 0.2 matched in client.
            nums = re.findall(r'[\d.]+', val)
            if len(nums) == 3:
                val = '{ %s }' % ' '.join(str(round(float(n) * LIGHTMAP_FOG_SCALE)) for n in nums)
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


def fix(bsp_paths, read_vmt, write_vmt, have_texture, say, stock=lambda name: False):
    """read_vmt(path under materials/, no ext) -> text or None; write_vmt(path, text) adds it to the package."""
    norm = lambda n: n.replace('\\', '/').lower().removesuffix('.vmt').removeprefix('materials/')
    fixed = {}

    def convert(name):
        """New name if the material (or its bottom) needed fixing, else None."""
        name = norm(name)
        if name in fixed:
            return fixed[name]
        fixed[name] = None  # guards $bottommaterial cycles
        text = read_vmt(name)
        if text is None or not is_water(text):
            return None
        b = re.search(r'"?\$bottommaterial"?\s+"?([^"\s]+)"?', text, re.I)
        bottom = convert(b.group(1)) if b else None
        # Not Valve's own L4D1 water and not already cheap: L4D2's expensive (reflect/refract) water drawn by L4D1
        # blanks the sky and every static prop in the frame (Detour Ahead 4's river under the bridge, 2026-10-19).
        expensive = not stock(name) and not re.search(r'"?\$forcecheap"?\s+"?1', text, re.I)
        if unsafe_water(text) or expensive:
            new_text = l4d1_water(text, have_texture)
            if b and not bottom:  # the bottom is fine as it is: point back at the original
                new_text = new_text.replace(f'"{PREFIX}{norm(b.group(1))}"', f'"{norm(b.group(1))}"')
        elif bottom:  # drawable itself, but its bottom was rewritten: same material, repointed bottom
            new_text = text[:b.start(1)] + bottom + text[b.end(1):]
        else:
            return None
        fixed[name] = PREFIX + name
        write_vmt(PREFIX + name, new_text)
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
