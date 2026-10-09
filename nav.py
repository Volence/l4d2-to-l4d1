import struct
class R:
    def __init__(s,d,p=0): s.d=d; s.p=p
    def u(s,fmt):
        v=struct.unpack_from('<'+fmt,s.d,s.p); s.p+=struct.calcsize('<'+fmt); return v if len(v)>1 else v[0]
def header(r):
    magic,ver,sub,bsp=r.u('IIII'); an=r.u('B'); pc=r.u('H')
    for i in range(pc): l=r.u('H'); r.p+=l
    r.u('B')  # hasUnnamedAreas
    e=r.d.index(b'\0',r.p); r.p=e+1  # L4D nav theme name, e.g. "default"
    r.u('B'); r.u('B')
    n=r.u('I'); return ver,sub,n
def area_base(r,ver):
    st=r.p
    aid,flags=r.u('II'); r.p+=24+8
    for d in range(4):
        c=r.u('I'); r.p+=4*c
    hs=r.u('B'); r.p+=hs*(4+12+1)
    ec=r.u('I')
    for i in range(ec):
        r.p+=4+1+4+1; sc=r.u('B'); r.p+=sc*5
    r.u('H')
    for d in range(2):
        c=r.u('I'); r.p+=4*c
    r.p+=8+16
    if ver>=16:
        c=r.u('I'); r.p+=c*5
        r.u('I')
    return aid
