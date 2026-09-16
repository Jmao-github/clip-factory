#!/usr/bin/env python3
"""G10 响度机检（0915，源 autocut EBU R128）：成片集成响度 -16±1 LUFS 且真峰值 <= -1.0 dBTP。
输出 loudness.json + 最后一行 LOUDNESS-PASS / LOUDNESS-FAIL。"""
import json, re, subprocess
ok=True; res=[]
import os
for c in json.load(open('built.json')):
    f=c['file'] if os.path.exists(c['file']) else c['slug']+'.mp4'   # promote 后 cand 已转正
    t=subprocess.run(['ffmpeg','-i',f,'-af','loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json','-f','null','-'],
                     capture_output=True,text=True).stderr
    d=json.loads(re.search(r'\{[^{}]*input_i[^{}]*\}',t,re.S).group(0))
    i=float(d['input_i']); tp=float(d['input_tp'])
    good = abs(i+16)<=1.0 and tp<=-1.0
    ok &= good
    res.append(dict(slug=c['slug'],lufs=i,tp=tp,ok=good))
    print(f"{c['slug']:32} {i:6.1f} LUFS  TP {tp:5.1f}  {'OK' if good else 'FAIL'}")
json.dump(res,open('loudness.json','w'),indent=1)
print('LOUDNESS-PASS' if ok else 'LOUDNESS-FAIL')
