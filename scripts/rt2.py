import os as _o; _o.chdir(_o.environ.get('WORKDIR','.'))
import json,os,re,subprocess,difflib
import mlx_whisper
FILLER=re.compile(r"^\s*(uh|um|erm)[,.]?\s*$",re.I)
WORDS=[w for s in json.load(open('whisper.json'))['segments'] for w in s.get('words',[])]
res=[]
import os
ONLY=os.environ.get('ONLY')
for c in json.load(open(os.environ.get('BUILT','built.json'))):
    if ONLY and c['slug']!=ONLY: continue
    f=c['file']
    dur=float(subprocess.run(['ffprobe','-v','error','-show_entries','format=duration','-of','csv=p=0',f],capture_output=True,text=True).stdout)
    parts=[]
    for st in range(0,int(dur)+1,30):
        wav=f'_x{st}.wav'
        subprocess.run(['ffmpeg','-v','error','-ss',str(st),'-t','30','-i',f,'-vn','-ac','1','-ar','16000',wav,'-y'],check=True)
        if os.path.getsize(wav)<8000: os.remove(wav); continue
        parts.append(mlx_whisper.transcribe(wav,path_or_hf_repo='mlx-community/whisper-large-v3-turbo',language='en',verbose=False,condition_on_previous_text=False)['text'].strip())
        os.remove(wav)
    got=re.findall(r"[a-z0-9']+",' '.join(parts).lower())
    # 0915: whisper 复读幻觉兜底（实测 'Survey'×37）——连续同词最多留 2 个
    dedup=[]
    for w in got:
        if len(dedup)>=2 and dedup[-1]==w and dedup[-2]==w: continue
        dedup.append(w)
    got=dedup
    exp=[]
    for sg in c['segs']:
        for w in WORDS:
            if sg['cut_a']<=w['start'] and w['end']<=sg['cut_b'] and not FILLER.match(w['word']):
                x=re.sub(r"[^a-z0-9']",'',w['word'].lower())
                if x: exp.append(x)
    ratio=difflib.SequenceMatcher(None,exp,got).ratio()
    if ratio<0.85 and not os.environ.get('RT2_RETRY'):
        # 0915: mlx-whisper 有进程级抖动（同片52%→重开进程97%实测）——低分拉起全新进程重测一次
        env=dict(os.environ, ONLY=c['slug'], RT2_RETRY='1', RT='_rt_retry.json')
        subprocess.run(['python3', os.path.abspath(__file__)], env=env)
        try:
            rr=[x for x in json.load(open('_rt_retry.json')) if x['slug']==c['slug']][0]
            if rr['ratio']>ratio:
                res.append(rr); print(f"{c['slug']:32} 重测(新进程) {rr['ratio']*100:5.1f}%"); continue
        except Exception: pass
    def anchor(ew,gw):
        if difflib.SequenceMatcher(None,ew,gw).ratio()>=0.70: return True
        content=[w for w in ew if len(w)>2 or w.isdigit()]
        hit=sum(1 for w in content if any(difflib.SequenceMatcher(None,w,g).ratio()>=0.8 for g in gw))
        return bool(content) and hit/len(content)>=0.75
    head=anchor(exp[:8],got[:12]); tail=anchor(exp[-8:],got[-12:])
    res.append(dict(slug=c['slug'],ratio=round(ratio,3),head_ok=head,tail_ok=tail,
                    head_exp=' '.join(exp[:8]),tail_exp=' '.join(exp[-8:])))
    print(f"{c['slug']:32} {ratio*100:5.1f}%  首 {'OK' if head else 'FAIL'}  尾 {'OK' if tail else 'FAIL'}")
rtp=os.environ.get('RT','retranscribe.json')
if ONLY and os.path.exists(rtp):   # 窄重跑：合并不覆盖
    new={r['slug']:r for r in res}
    res=[new.pop(r['slug'],r) for r in json.load(open(rtp))]+list(new.values())
json.dump(res,open(rtp,'w'),ensure_ascii=False,indent=1)
