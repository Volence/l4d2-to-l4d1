import struct,sys,os
def read_cstr(f):
    b=b''
    while True:
        c=f.read(1)
        if c in (b'\0',b''): return b.decode('latin1')
        b+=c
def entries(path):
    f=open(path,'rb')
    sig,ver,tree=struct.unpack('<III',f.read(12))
    assert sig==0x55aa1234
    if ver==2: f.read(16)
    hdr=12+(16 if ver==2 else 0)
    out=[]
    while True:
        ext=read_cstr(f)
        if not ext: break
        while True:
            d=read_cstr(f)
            if not d: break
            while True:
                n=read_cstr(f)
                if not n: break
                crc,pre,arc,off,ln,term=struct.unpack('<IHHIIH',f.read(18))
                predata=f.read(pre)
                p=(d.strip()+'/' if d.strip() else '')+n+'.'+ext
                out.append((p,arc,off,ln,predata))
    return f,hdr+tree,out
if __name__=='__main__':
    path,dest=sys.argv[1],sys.argv[2]
    f,base,es=entries(path)
    for p,arc,off,ln,pre in es:
        assert arc==0x7fff,arc
        f.seek(base+off); data=pre+f.read(ln)
        o=os.path.join(dest,p); os.makedirs(os.path.dirname(o),exist_ok=True)
        open(o,'wb').write(data)
    print(len(es),'files')
