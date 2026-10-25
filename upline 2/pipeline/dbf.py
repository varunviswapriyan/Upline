import struct, pandas as pd, sys
def read_dbf(path, maxrows=None, cols=None):
    with open(path,'rb') as f:
        hdr=f.read(32)
        n=struct.unpack('<I',hdr[4:8])[0]; hl,rl=struct.unpack('<HH',hdr[8:12])
        fields=[]
        while True:
            d=f.read(32)
            if d[0]==0x0D: break
            name=d[:11].split(b'\0')[0].decode('latin1'); t=chr(d[11]); ln=d[16]
            fields.append((name,t,ln))
        f.seek(hl)
        m=n if maxrows is None else min(n,maxrows)
        raw=f.read(m*rl)
    rows=[]; 
    for i in range(m):
        rec=raw[i*rl:(i+1)*rl]; pos=1; r={}
        for name,t,ln in fields:
            v=rec[pos:pos+ln].decode('latin1').strip(); pos+=ln
            if cols is None or name in cols: r[name]=v
        rows.append(r)
    return pd.DataFrame(rows), fields, n
