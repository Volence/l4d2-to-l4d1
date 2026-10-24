#!/usr/bin/env python3
"""Rebuild L4D2 onslaughts (VScript Director Scripts that keep the horde coming) for L4D1.

    ./onslaught.py <name> [<name> ...]      write the block into out/<name>/rotoblin/stripper/<map>.cfg
    ./onslaught.py --list                   print the table

L4D1 has no VScript, so a Director Script such as `MobSpawnMinTime = 1, ResetMobTimer()` that kept mobs
coming until the survivors pressed a button simply does nothing in a conversion: the alarm plays and no horde
comes. Measured on the strip rig 2026-10-23 (commons deleted as they spawned, so the common limit hid
nothing): one PanicEvent spawned 50 commons and ended; with director_panic_forever 1 the same panic gave
150 then 200 a minute and kept going until the cvar went back to 0, after which none came. So an onslaught
becomes: PanicEvent + director_panic_forever 1 where the map began the script, director_panic_forever 0
where it ended it. The director still picks the spawn spots, so nothing is hand placed.

Two engine rules shape the entities (L4D1 server, see ~/l4d/source InputPanicEvent / OnMapInvokedPanicEvent):
- A map PanicEvent is refused for 90 s after the last one. The event's own panic often fired seconds earlier,
  so a retry timer fires PanicEvent every 5 s for the first 95 s; with panic_forever on, the first one the
  director accepts starts a panic that never ends, and one already running is simply kept going.
- director_panic_forever is a cheat cvar: plain `director_panic_forever 1` is refused with sv_cheats 0, but
  `sm_cvar` sets it (checked on the rig with sv_cheats 0), so a point_servercommand sends sm_cvar.

The cvar outlives the round, so every round start puts it back to 0 (logic_auto OnMapSpawn and
OnMultiNewRound), and cfg/riverside/shared.cfg does the same on every map load for maps that are not ours.

Each start/end is matched by hammerid (as the Comp Rework port does), with the output and delay the original
L4D2 map used for its BeginScript / EndScript, or the Comp Rework cfg's where Comp moved them. An onslaught
with no end runs until the round ends. The block sits between markers in the
map's cfg, so a rerun replaces it; compstripper.py runs this after every port.
"""
import glob, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BEGIN = '; ===== [L4D1] onslaughts (onslaught.py) ====='
END = '; ===== [L4D1] end of onslaughts ====='

# map: (campaign, start, end, note). start/end = (hammerid, output, delay); end None = until the round ends.
TABLE = {
    'cwm2_warehouse': ('carriedoff', (15876, 'OnTrigger', 0.01), (15872, 'OnTrigger', 30),
                       'c6m2_minifinale: doors open (door_open_relay) until 30 s after the switch (button_relay)'),
    'cwm3_drain': ('carriedoff', (3589, 'OnTrigger', 1), (153153, 'OnTrigger', 30),
                   'cwm_onslaught: first sparks (relay_start) until 30 s after the second (relay_start_02)'),
    'cdta_02road': ('detourahead', (552969, 'OnTrigger', 1), (1049369, 'OnPressed', 0),
                    'da2gauntlet: the trap (traprelay2) until the button (gbutton), as Comp Rework ends it'),
    'cdta_04onarail': ('detourahead', (435108, 'OnTrigger', 0.35), (598550, 'OnPass', 15),
                       'da4bridge: boxcar button (trainrelay1) until 15 s after the boxcar reaches boxcarpath5'),
    'hf02_thesteeple': ('hauntedforest', (238573, 'OnStartTouch', 3), (238621, 'OnPressed', 0),
                        'hf02_rolling_tunnel (Comp: _promod): the tunnel alarm until the button that stops it'),
    'l4d2_diescraper2_streets_361': ('diescraper', (881077, 'OnTrigger', 1.5), (652799, 'OnIn', 0),
                                     'diescraper2_onslaught1_vs + _2_vs: lobby door (lobby_panic_vs) until alarm_button2'),
    'l4d2_diescraper3_mid_361': ('diescraper', (1089328, 'OnTrigger', 40), (843176, 'OnIn', 1),
                                 'diescraper3_minifinale (Comp: _mid_34_minifinale_promod at 40 s): generator '
                                 '(gauntlet_coop) until alarm_button2 (spawned by alarm_button_template)'),
}
# Left alone on purpose: Comp Rework filters out the trigger that started these, so they stay gone.
#   x1m3_city x1m3_endrun (scriptitrigger, "Remove crow hordes"), x1m4_forest x1m4_ambush (korribeep1-3).
# Not onslaughts: x1m2_metsa never ran in L4D2 either (relay_mappikaks is only touched by an empty AddOutput);
#   diescraper2_onslaught3 at the elevator Comp turns into two PanicEvents; diescraper1's sewer horde is
#   killed in versus (info_gamemode OnVersus); *_passive / *_noboss / *_quiet only retune pacing, bosses or SI.

PREFIX = 'l4d1_onslaught'


def block(m):
    camp, start, end, note = TABLE[m]
    cmd = f'{PREFIX}_cmd,Command,sm_cvar director_panic_forever'
    lines = [BEGIN, f'; {note}', '; See l4d2to1/onslaught.py: PanicEvent + director_panic_forever 1 at the start,',
             '; 0 at the end and at every round start; a 5 s PanicEvent retry rides out the 90 s map panic cooldown.',
             'add:',
             '{', '\t"classname" "point_servercommand"', f'\t"targetname" "{PREFIX}_cmd"', '}',
             '{', '\t"classname" "logic_timer"', f'\t"targetname" "{PREFIX}_retry"', '\t"StartDisabled" "1"',
             '\t"RefireTime" "5"', '\t"OnTimer" "director,PanicEvent,,0,-1"', '}',
             '{', '\t"classname" "logic_relay"', f'\t"targetname" "{PREFIX}_on"',
             f'\t"OnTrigger" "{cmd} 1,0,-1"', '\t"OnTrigger" "director,PanicEvent,,0.1,-1"',
             f'\t"OnTrigger" "{PREFIX}_retry,Enable,,0.1,-1"', f'\t"OnTrigger" "{PREFIX}_retry,Disable,,95,-1"', '}',
             '{', '\t"classname" "logic_relay"', f'\t"targetname" "{PREFIX}_off"',
             f'\t"OnTrigger" "{cmd} 0,0,-1"', f'\t"OnTrigger" "{PREFIX}_retry,Disable,,0,-1"',
             f'\t"OnTrigger" "{PREFIX}_on,Disable,,0,-1"', '}',
             '{', '\t"classname" "logic_auto"',
             f'\t"OnMapSpawn" "{cmd} 0,0,-1"', f'\t"OnMultiNewRound" "{cmd} 0,0,-1"', '}',
             'modify:']
    for (hid, out, delay), relay in ((start, 'on'), (end, 'off')) if end else ((start, 'on'),):
        lines += ['{', '\tmatch:', '\t{', f'\t\t"hammerid" "{hid}"', '\t}', '\tinsert:', '\t{',
                  f'\t\t"{out}" "{PREFIX}_{relay},Trigger,,{delay:g},-1"', '\t}', '}']
    return '\n'.join(lines + [END]) + '\n'


def strip(text):
    return re.sub(r'\n*' + re.escape(BEGIN) + r'.*?' + re.escape(END) + r'\n?', '', text, flags=re.S).rstrip('\n') + '\n'


def apply(path, m):
    text = strip(open(path, encoding='latin1').read())
    open(path, 'w', encoding='latin1').write(text + ('\n' + block(m) if m in TABLE else ''))


def main(names):
    done = []
    for m, (camp, *_rest) in TABLE.items():
        if camp in names and not os.path.exists(os.path.join(HERE, 'out', camp, 'rotoblin', 'stripper', m + '.cfg')):
            sys.exit(f'out/{camp}/rotoblin/stripper/{m}.cfg is missing (run compstripper.py {camp} first)')
    for camp in names:
        for p in sorted(glob.glob(os.path.join(HERE, 'out', camp, 'rotoblin', 'stripper', '*.cfg'))):
            m = os.path.basename(p)[:-4]
            if m in TABLE or BEGIN in open(p, encoding='latin1').read():
                apply(p, m)  # a map dropped from the table loses its block
                done.append(m if m in TABLE else m + ' (block removed)')
    return done


if __name__ == '__main__':
    if '--list' in sys.argv:
        for m, (camp, s, e, note) in TABLE.items():
            print(f'{camp:14s} {m:30s} {note}')
        sys.exit()
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if not args:
        sys.exit(__doc__)
    print('\n'.join(main(args)) or 'nothing in the table for ' + ' '.join(args))
