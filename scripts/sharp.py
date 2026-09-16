import os as _o; _o.chdir(_o.environ.get('WORKDIR','.'))
import subprocess, json, os, shutil
import numpy as np
from PIL import Image
def lap_var(path, t):
    subprocess.run(['ffmpeg','-v','error','-ss',str(t),'-i',path,'-frames:v','1','/tmp/_s.png','-y'],check=True)
    g=np.asarray(Image.open('/tmp/_s.png').convert('L'),dtype=float)
    lap=(-4*g[1:-1,1:-1]+g[:-2,1:-1]+g[2:,1:-1]+g[1:-1,:-2]+g[1:-1,2:])
    return float(lap.var())
pairs=[('01-jason-daily-driver',[20.0,28.0]),
       ('03-fathin-verification-gap',[20.0,30.0]),
       ('04-jason-memory-tiers',[20.0,35.0]),
       ('05-fathin-voice-clone',[16.0,30.0,40.0])]
res=[]
for slug,ts in pairs:
    oldp=f'v1_backup/{slug}.mp4'
    if not os.path.exists(oldp):
        m={'04-jason-memory-tiers':'v1_backup/Clip 4 - Memory Is The Only Difference.mp4',
           '05-fathin-voice-clone':'v1_backup/Clip 5 - Clone Your Voice With An LLM.mp4'}
        oldp=m[slug]
    for t in ts:
        v1=lap_var(oldp,t); v2=lap_var(f'{slug}.mp4',t)
        res.append(dict(slug=slug,t=t,v1=round(v1,1),v2=round(v2,1),gain=round(v2/max(v1,1e-6),2)))
        print(f"{slug} @{t:5.1f}s  v1={v1:8.1f}  v2={v2:8.1f}  gain x{v2/max(v1,1e-6):.2f}")
json.dump(res,open('sharpness.json','w'))
pass  # 落在 WORKDIR
