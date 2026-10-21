import re,glob,os,sys
W=sys.argv[1]
os.chdir('/home/volence/l4d/l4d2to1/out')
for p in sorted(glob.glob(W+'/port/*.cfg')):
    m=os.path.basename(p)
    sk=glob.glob('*/rotoblin/stripper/'+m)
    body=open(p,encoding='latin1').read()
    head=[]; ammo=''
    if sk:
        t=open(sk[0]).read()
        if t.startswith('; Ported from'):  # already assembled once: take the skeleton from git? no: keep its header
            t=t.split('\n',4)[4]
        for l in t.split('\n'):
            if l.startswith('; ####') or l.startswith('; ====='): break
            head.append(l)
        a=re.search(r'^add:\n\{[^{}]*"weapon_ammo_spawn"[^{}]*\}',t,re.M)
        if a and m!='cwm3_drain.cfg':
            ammo='\n\n; --- [L4D1] start saferoom ammo pile (the conversion has none near info_player_start)\n'+a.group(0)+'\n'
    head=[('; Positions are from the BSP and game flow (flowdump); check them in game with getpos / !cur.' if 'from the BSP and game flow' in l else l) for l in head if 'then edited by hand' not in l]
    intro=['; Ported from SirPlease/L4D2-Competitive-Rework cfg/stripper/zonemod/maps/'+m,
           '; by l4d2to1/stripper2to1.py, matches checked against the converted BSP. Lines tagged [L4D1] say',
           '; what changed; blocks commented out under them have no L4D1 equivalent.',';']
    open(W+'/final/'+m,'w',encoding='latin1').write('\n'.join(intro+head)+'\n'+body.rstrip('\n')+ammo+'\n')
