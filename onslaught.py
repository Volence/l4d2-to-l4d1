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

What shapes the entities:
- One PanicEvent at the start, nothing more. A PanicEvent while a panic runs RESTARTS it (log: StartPanicEvent,
  ClearPendingMobCount "All mobs cleared", STAGE_INITIAL_DELAY, and the mega mob scream again): a 5 s retry
  timer, first written for a 90 s map panic cooldown read in the server source, made Carried Off 2 scream every
  ~5 s in the owner's test 2026-10-23 and was removed. If the map's own panic fired just before, the director
  either takes ours (one more scream) or keeps the running one; panic_forever keeps whichever goes on.
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
    'l4d2_diescraper3_mid_361': ('diescraper', (1089328, 'OnTrigger', 8), (843176, 'OnIn', 1),
                                 'diescraper3_minifinale: generator (gauntlet_coop) until alarm_button2 (spawned by '
                                 'alarm_button_template); on with the lever\'s own 8 s panic, not at Comp\'s 40 s '
                                 '_promod: the 40 s start restarted that panic and felt weak (owner, 2026-10-23)'),
}
# Left alone on purpose: Comp Rework filters out the trigger that started these, so they stay gone.
#   x1m3_city x1m3_endrun (scriptitrigger, "Remove crow hordes"), x1m4_forest x1m4_ambush (korribeep1-3).
# Not onslaughts: x1m2_metsa never ran in L4D2 either (relay_mappikaks is only touched by an empty AddOutput);
#   diescraper2_onslaught3 at the elevator Comp turns into two PanicEvents; diescraper1's sewer horde is
#   killed in versus (info_gamemode OnVersus); *_passive / *_noboss / *_quiet only retune pacing, bosses or SI.

# L4D2 gauntlet finales (run to the rescue through an endless horde): deploy plugin l4d_gauntlet_finale runs them
# (mapinfo gauntlet_finale 1: flow goal at the rescue, the finale goes straight to its escape stage, whose horde is
# the endless one, and only the map's own tank). The cfg only says where the map's tank comes and where the horde
# ends, at the triggers that sent ForceTankSpawn and GauntletStopPanic in L4D2.
# map: (campaign, tank, stop, note). tank/stop = (hammerid, output, delay). stop None = the horde runs until the round
# ends (only paused while the map's tank lives).
GAUNTLET = {
    'hf04_escape': ('hauntedforest', (59287, 'OnStartTouch', 0), (152285, 'OnStartTouch', 0),
                    'hf04_escape gauntlet: tank at the tunnel end trigger (ForceTankSpawn + GauntletStopPanic in '
                    'L4D2; ForceTankSpawn does nothing in a gauntlet, so the tank waits for the commons: mapinfo '
                    'gauntlet_tank_wait 1), horde over at the boat dock trigger (relay_stopgauntlet)'),
    'cwm4_building': ('carriedoff', (216799, 'OnTrigger', 0), None,
                      'cwm_finale gauntlet: trigger_stopgauntlet sent GauntletStopPanic, and the L4D2 gauntlet then '
                      'spawned its tank once the commons were dead (Comp teleported it to a fixed spot, '
                      'cwm4_building_tank_helper_promod) and brought the horde back when it died; here the same '
                      'trigger pauses the horde and the plugin spawns the tank there (mapinfo gauntlet_tank_wait 1)'),
}

PREFIX = 'l4d1_onslaught'


def wanted(m):
    return m in TABLE or m in GAUNTLET


def gauntlet_block(m):
    camp, tank, stop, note = GAUNTLET[m]
    cmd = f'{PREFIX}_gauntlet_cmd,Command'
    lines = [BEGIN, f'; {note}', '; See l4d2to1/onslaught.py GAUNTLET and deploy plugin l4d_gauntlet_finale (mapinfo',
             '; gauntlet_finale 1, gauntlet_goal, gauntlet_tank_pos).',
             'add:',
             '{', '\t"classname" "point_servercommand"', f'\t"targetname" "{PREFIX}_gauntlet_cmd"', '}',
             'modify:']
    for trig, arg in ((tank, 'gauntlet_tank'), (stop, 'gauntlet_horde 0')):
        if trig is None:
            continue
        hid, out, delay = trig
        lines += ['{', '\tmatch:', '\t{', f'\t\t"hammerid" "{hid}"', '\t}', '\tinsert:', '\t{',
                  f'\t\t"{out}" "{cmd},{arg},{delay:g},-1"', '\t}', '}']
    return '\n'.join(lines + [END]) + '\n'


def block(m):
    camp, start, end, note = TABLE[m]
    cmd = f'{PREFIX}_cmd,Command,sm_cvar director_panic_forever'
    lines = [BEGIN, f'; {note}', '; See l4d2to1/onslaught.py: PanicEvent + director_panic_forever 1 at the start,',
             '; 0 at the end and at every round start.',
             'add:',
             '{', '\t"classname" "point_servercommand"', f'\t"targetname" "{PREFIX}_cmd"', '}',
             '{', '\t"classname" "logic_relay"', f'\t"targetname" "{PREFIX}_on"',
             f'\t"OnTrigger" "{cmd} 1,0,-1"', '\t"OnTrigger" "director,PanicEvent,,0.1,-1"', '}',
             '{', '\t"classname" "logic_relay"', f'\t"targetname" "{PREFIX}_off"',
             f'\t"OnTrigger" "{cmd} 0,0,-1"', f'\t"OnTrigger" "{PREFIX}_on,Disable,,0,-1"', '}',
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
    extra = block(m) if m in TABLE else gauntlet_block(m) if m in GAUNTLET else ''
    open(path, 'w', encoding='latin1').write(text + ('\n' + extra if extra else ''))


def main(names):
    done = []
    for m, (camp, *_rest) in list(TABLE.items()) + list(GAUNTLET.items()):
        if camp in names and not os.path.exists(os.path.join(HERE, 'out', camp, 'rotoblin', 'stripper', m + '.cfg')):
            sys.exit(f'out/{camp}/rotoblin/stripper/{m}.cfg is missing (run compstripper.py {camp} first)')
    for camp in names:
        for p in sorted(glob.glob(os.path.join(HERE, 'out', camp, 'rotoblin', 'stripper', '*.cfg'))):
            m = os.path.basename(p)[:-4]
            if wanted(m) or BEGIN in open(p, encoding='latin1').read():
                apply(p, m)  # a map dropped from the table loses its block
                done.append(m if wanted(m) else m + ' (block removed)')
    return done


if __name__ == '__main__':
    if '--list' in sys.argv:
        for m, (camp, s, e, note) in list(TABLE.items()) + list(GAUNTLET.items()):
            print(f'{camp:14s} {m:30s} {note}')
        sys.exit()
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if not args:
        sys.exit(__doc__)
    print('\n'.join(main(args)) or 'nothing in the table for ' + ' '.join(args))
