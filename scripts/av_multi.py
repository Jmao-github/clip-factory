import os as _o; _o.chdir(_o.environ.get('WORKDIR','.'))
#!/usr/bin/env python3
"""逐段图文机检（3 帧多数决版）：每段取 25%/50%/75% 三帧，≥2 帧 MISMATCH 才判段级 MISMATCH。
瞬时导航/过渡帧不应一票否决一个语义段。"""
import json,subprocess,sys
BUILT=sys.argv[1] if len(sys.argv)>1 else 'promo_built.json'
OUTJ=sys.argv[2] if len(sys.argv)>2 else 'promo_avcheck.json'
clips=json.load(open(BUILT))
S=_o.environ['SRC']
ONLY=_o.environ.get('ONLY')
if ONLY: clips=[c for c in clips if c['slug']==ONLY]
res=[]
segall=[(c,i,sg) for c in clips for i,sg in enumerate(c['segs'])]
for c,i,sg in segall:
    a,b=sg['cut_a'],sg['cut_b']
    votes=[]
    for frac in (0.25,0.5,0.75):
        t=a+(b-a)*frac
        p=f"avf_{c['slug']}_{i}_{int(frac*100)}.png"
        subprocess.run(['ffmpeg','-v','error','-i',S,'-ss',str(t),'-frames:v','1','-vf','crop=960:488:0:132',p,'-y'],check=True)
        out=subprocess.run([sys.executable,_os.path.join(_os.path.dirname(_os.path.abspath(__file__)),'avcheck.py'),p,sg['text'][:300]],capture_output=True,text=True).stdout.strip().split('\n')
        votes.append('MISMATCH' in out[-1])
    verdict='MISMATCH' if sum(votes)>=2 else 'MATCH'
    res.append(dict(clip=c['slug'],seg=i,title=sg['title'],a=a,b=b,votes=votes,verdict=verdict))
    print(f"{c['slug']}/seg{i} {verdict} (votes {votes})  {sg['title']}")
if ONLY and _o.path.exists(OUTJ):   # 窄重跑：按 clip+seg 合并不覆盖
    new={(r['clip'],r['seg']):r for r in res}
    res=[new.pop((r['clip'],r['seg']),r) for r in json.load(open(OUTJ))]+list(new.values())
json.dump(res,open(OUTJ,'w'),ensure_ascii=False,indent=1)
bad=[r for r in res if r['verdict']=='MISMATCH']
print('SEGMENTS-FAIL' if bad else 'SEGMENTS-PASS')
