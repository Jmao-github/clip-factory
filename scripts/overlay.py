#!/usr/bin/env python3
import json, os, re, subprocess
from PIL import Image, ImageDraw, ImageFont
import os as _o; _o.chdir(_o.environ.get('WORKDIR','.'))
FB='/System/Library/Fonts/Supplemental/Arial Bold.ttf'
fcap=ImageFont.truetype(FB,44); flab=ImageFont.truetype(FB,30)
W,H=1280,650
WORDS=[w for s in json.load(open('whisper.json'))['segments'] for w in s.get('words',[])]
import os
clips=json.load(open(os.environ.get('BUILT','built.json')))

SUBFIX={'hyperframe':'HyperFrame','Hyperframe':'HyperFrame','crocs':'crux','codex':'Codex',
        'after effects':'After Effects','javascript':'JavaScript'}
# 本场专名表（阶段0建，whisper 必错的品牌/人名前置修正）；场表覆盖默认表
if os.path.exists('glossary.json'): SUBFIX.update(json.load(open('glossary.json')))
FILLER_TOK = re.compile(r'^(uh|um|erm|mm+)[.,!?;:]*$', re.I)

def fix(t):
    for k,v in SUBFIX.items(): t=re.sub(re.escape(k),v,t)
    return t

def fix_tokens(toks):
    """专名表按 token 序列改写（0915晚实证立）：
    ① whisper 把 '2.5' 拆成 '2'+'.5' → 先并回去，否则 'GP image 2 .5' 永远匹配不上表
    ② 多词表项（'11 lab' / 'byte plus' / 'GP image 2.5'）此前只在单屏字幕文本上 re.sub，
       一旦被切到两屏就整条失效——改成在词序列上匹配，与分屏无关。
    被并掉的 token 置空串（保留其时间戳参与断屏判定，只是不进文本）。"""
    toks = list(toks)
    for i in range(1, len(toks)):
        a, b = toks[i-1], toks[i]
        if a and b.startswith('.') and len(b) > 1 and b[1].isdigit() and a[-1].isdigit():
            toks[i-1] = a + b; toks[i] = ''
    for k, v in SUBFIX.items():
        kt = k.split()
        if len(kt) == 1:
            for i, t in enumerate(toks):
                if t: toks[i] = re.sub(re.escape(k), v, t)
            continue
        i = 0
        while i < len(toks):
            j = i; hit = []
            for key in kt:
                while j < len(toks) and not toks[j]: j += 1
                if j >= len(toks): hit = None; break
                cur = toks[j]
                if cur == key or cur.rstrip('.,!?;:') == key: hit.append(j); j += 1
                else: hit = None; break
            if hit:
                last = toks[hit[-1]]
                tail = last[len(kt[-1]):] if last.startswith(kt[-1]) else ''
                toks[hit[0]] = v + tail
                for x in hit[1:]: toks[x] = ''
                i = j
            else:
                i += 1
    return toks

def cues_for(spans):
    total = sum(b - a for a, b in spans)
    def to_out(w):
        """词→成片时间轴：按与 span 的重叠取最大一段并夹紧。
        0915晚修：旧实现要求 start/end 都严格落在 span 内，凡是被帧对齐/声学起点模型削掉几十毫秒的词
        （'best' 'proper' 'me'）整词从字幕消失——音频里明明还在，字幕却变成 'everyone said it is but for'。
        判据：重叠 ≥35% 词长或 ≥0.15s 才算在片内（被整词删掉的 uh/um 重叠=0，仍然丢弃）。"""
        off = 0.0; best = None
        for a, b in spans:
            ov = min(w['end'], b) - max(w['start'], a)
            if best is None or ov > best[0]:
                best = (ov, off + max(min(w['start'], b), a) - a, off + max(min(w['end'], b), a) - a)
            off += b - a
        if best is None: return None
        d = w['end'] - w['start']
        if d <= 0:
            return (best[1], best[2]) if best[0] >= 0 else None
        if best[0] >= 0.35 * d or best[0] >= 0.15: return best[1], best[2]
        return None
    mapped = []
    for w in WORDS:
        r = to_out(w)
        if r: mapped.append((r[0], r[1], w))
    toks = fix_tokens([m[2]['word'].strip() for m in mapped])
    # 口头禅永不上字幕：顺滑层删整词后仍可能在剪口留残片，whisper 源时间戳又能漂 0.3-0.8s，
    # 宽松映射会把它捞回字幕（0915晚 clip02 实证：G11/G12 两道声学 gate 都判该剪口干净，字幕却冒出 'Uh,'）
    toks = ['' if FILLER_TOK.match(t) else t for t in toks]
    cues = []; cur = []; cs = None; oe = 0; prev_e = None
    def flush():
        nonlocal cur, cs
        if cur: cues.append([round(cs, 3), round(oe, 3), ' '.join(cur)])
        cur = []; cs = None
    for (o, e, w), tok in zip(mapped, toks):
        if prev_e is not None and o - prev_e > 0.5: flush()
        if cs is not None and e - cs > 2.55: flush()
        if tok:
            if cs is None: cs = o
            cur.append(tok)
        oe = e; prev_e = e
        if not cur: continue
        long_enough = oe - cs >= 1.1
        if (len(cur) >= 5 and long_enough) or oe - cs >= 1.9 or (tok.endswith(('.', '?', '!')) and long_enough):
            flush()
    flush()
    return cues

def wrap(d,txt,maxw,font):
    out=[];cur=''
    for w in txt.split():
        t=(cur+' '+w).strip()
        if d.textlength(t,font=font)<=maxw: cur=t
        else: out.append(cur); cur=w
    if cur: out.append(cur)
    return out[:2]

ONLY=os.environ.get('ONLY')
for c in clips:
    if ONLY and c['slug']!=ONLY: continue
    spans=[tuple(x) for x in c['spans']]
    cues=cues_for(spans); c['cues']=cues
    d0=f"caps/{c['slug']}"; os.makedirs(d0,exist_ok=True)
    def band_needs_backdrop(t_mid, y_top, y_bot):
        # 0915 自动判定：字幕落区若是「暗底+含白字」→ 垫带（防两层白字交叠）；纯亮底（幻灯片）不垫
        import numpy as _np
        r=subprocess.run(['ffmpeg','-v','error','-ss',str(max(t_mid,0.05)),'-i',c['base'],'-frames:v','1',
            '-vf',f'crop={W-180}:{int(y_bot-y_top)}:90:{int(y_top)},format=gray','-f','rawvideo','-'],capture_output=True)
        if not r.stdout: return False
        a2=_np.frombuffer(r.stdout,_np.uint8)
        return a2.mean()<105 and (a2>200).mean()>0.012
    for i,(a,b,txt) in enumerate(cues):
        img=Image.new('RGBA',(W,H),(0,0,0,0)); dr=ImageDraw.Draw(img)
        lines=wrap(dr,txt,W-190,fcap); lh=54; y0=H-96-lh*(len(lines)-1)
        if c.get('cap_backdrop') or band_needs_backdrop((a+b)/2, y0-10, y0+lh*(len(lines)-1)+56):
            mw=max(dr.textlength(ln,font=fcap) for ln in lines)
            x0=(W-mw)/2
            dr.rounded_rectangle([x0-22,y0-10,x0+mw+22,y0+lh*(len(lines)-1)+56],radius=12,fill=(10,10,12,200))
        for j,ln in enumerate(lines):
            tw=dr.textlength(ln,font=fcap); x=(W-tw)/2; y=y0+j*lh
            for dx in range(-3,4):
                for dy in range(-3,4):
                    if dx*dx+dy*dy<=9: dr.text((x+dx,y+dy),ln,font=fcap,fill=(0,0,0,240))
            dr.text((x,y),ln,font=fcap,fill=(255,255,255,255))
        img.save(f'{d0}/c{i:03d}.png')
    hbox=[]  # 高亮框已废除（0906 负责人拍板）
    c['hbox_rendered']=hbox
    labs=[]
    def draw_label(lab, t0, t1):
        img=Image.new('RGBA',(W,H),(0,0,0,0)); dr=ImageDraw.Draw(img)
        tw=dr.textlength(lab,font=flab)
        dr.rounded_rectangle([44,36,44+tw+40,36+52],radius=10,fill=(15,15,18,225))
        dr.text((64,48),lab,font=flab,fill=(120,230,160,255))
        p=f'{d0}/lab{len(labs):02d}.png'; img.save(p); labs.append([t0,t1,p])
    if c.get('seg_labels'):   # 0915: 标签跟观点段走（一个观点=一个标题），不再绑机位
        for s0,s1,lab in c['seg_labels']:
            if lab: draw_label(lab, s0, s1)
    else:
        for sh in c['shots']:
            for j,(t,lab) in enumerate(sh.get('labels',[])):
                if not lab: continue
                nxt=sh['labels'][j+1][0] if j+1<len(sh['labels']) else sh['b']
                draw_label(lab, t, nxt)
    c['labels_rendered']=labs
    T=float(c.get('tempo',1.0))   # 0915 语音加速（1.0-1.15 变速不变调）；字幕/标签时间轴同缩
    inputs=['-i',c['base']]; ov=[];n=1
    for i,(a,b,_) in enumerate(cues): inputs+=['-i',f'{d0}/c{i:03d}.png']; ov.append((n,a/T,b/T)); n+=1
    for (a,b,p) in labs: inputs+=['-i',p]; ov.append((n,a/T,b/T)); n+=1
    for (a,b,p) in hbox: inputs+=['-i',p]; ov.append((n,a/T,b/T)); n+=1
    chain=[];prev='[0:v]'
    if T!=1.0:
        chain.append(f'[0:v]setpts=PTS/{T}[vt]'); prev='[vt]'
    for k,(idx,a,b) in enumerate(ov):
        lbl=f'[v{k}]'; chain.append(f"{prev}[{idx}:v]overlay=0:0:enable='between(t,{a:.3f},{b:.3f})'{lbl}"); prev=lbl
    open(f'fc_{c["slug"]}.txt','w').write(';'.join(chain))
    outf=f"{c['slug']}.cand.mp4"   # 候选片：全 gate 过后由 promote.py 替换正式片，旧有效成片在此之前不被触碰
    # 0915 响度标准化（源 autocut/EBU R128，同域实测值）：两遍式——先测 base，终渲线性应用，避免单遍动态模式的抽吸感
    mj=subprocess.run(['ffmpeg','-i',c['base'],'-af','loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json','-f','null','-'],capture_output=True,text=True).stderr
    m=re.search(r'\{[^{}]*input_i[^{}]*\}',mj,re.S); ln=json.loads(m.group(0))
    tempo_af=f"atempo={T}," if T!=1.0 else ""
    af=tempo_af+(f"loudnorm=I=-16:TP=-1.5:LRA=11:measured_I={ln['input_i']}:measured_TP={ln['input_tp']}"
        f":measured_LRA={ln['input_lra']}:measured_thresh={ln['input_thresh']}:offset={ln['target_offset']}:linear=true"+",alimiter=limit=0.84:level=false")
    c['loudnorm']=dict(input_i=ln['input_i'],input_tp=ln['input_tp'])
    subprocess.run(['ffmpeg','-v','error']+inputs+['-filter_complex_script',f'fc_{c["slug"]}.txt','-map',prev,'-map','0:a',
        '-c:v','libx264','-preset','slow','-crf','16','-pix_fmt','yuv420p',
        '-af',af,'-c:a','aac','-b:a','192k','-ar','48000','-movflags','+faststart',outf,'-y'],check=True)
    c['file']=outf
    dur=float(subprocess.run(['ffprobe','-v','error','-show_entries','format=duration','-of','csv=p=0',outf],capture_output=True,text=True).stdout)
    print(f"{c['slug']}: {dur:.1f}s | 字幕{len(cues)}屏 | 标签{len(labs)}")
json.dump(clips,open(os.environ.get('BUILT','built.json'),'w'),ensure_ascii=False,indent=1)
