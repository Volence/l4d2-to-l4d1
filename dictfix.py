#!/usr/bin/env python3
"""Put an L4D1 string table dictionary into a converted BSP: dictfix.py <map.bsp> <dictionary.dict>

A BSP carries stringtable_dictionary.dct in its pak; the engine encodes precache strings as indexes into it.
Converted maps keep the dictionary L4D2 built, which misses L4D1's sounds and scenes. Starting a SourceTV demo
writes every string table into one 96000-byte buffer (CHLTVDemoRecorder::WriteServerInfo), and without the
dictionary the tables do not fit: Host_Error "Overflow error writing string table baseline", which kills a
dedicated server (Carried Off, match 727 on Dallas, 2026-10-18). L4D1 builds the dictionary with the server
command `stringtabledictionary` on the loaded map; on Linux it cannot pack it (no bsppack) and leaves it in
reslists/<map>.dict, which this script packs. The client reads the same file from the same BSP.
"""
import io, sys, zipfile
from waterfix import _lumps, replace_lumps

NAME = 'stringtable_dictionary.dct'


def put_dictionary(bsp, dictionary):
    d = open(bsp, 'rb').read()
    o, n = _lumps(d)[40][:2]
    old = zipfile.ZipFile(io.BytesIO(d[o:o + n]))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_STORED) as z:  # BSP paks must stay uncompressed
        for info in old.infolist():
            if info.filename.lower() not in (NAME, 'stringtable_dictionary_xbox.dct'):
                z.writestr(info.filename, old.read(info))
        z.writestr(NAME, dictionary)
    replace_lumps(bsp, {40: buf.getvalue()})


if __name__ == '__main__':
    put_dictionary(sys.argv[1], open(sys.argv[2], 'rb').read())
