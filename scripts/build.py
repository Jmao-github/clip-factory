#!/usr/bin/env python3
"""wk2 成片管线：选段 → 词边界 → 顺滑层 → 阶梯机位 → 字幕/标签 → 渲染。"""
import json, os, re, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from smooth import build as smooth_build

import os as _o; _o.chdir(_o.environ.get('WORKDIR','.'))
SRC = _o.environ['SRC']
W = json.load(open('whisper.json'))['segments']
# 0915晚 声学真相源（负责人抓残响后立；smooth 声学精修的输入）：audio.wav 16k → rms(t)/zcr(t)
def _load_acoustic():
    import wave
    import numpy as np
    try:
        wf = wave.open('audio.wav', 'rb')
        pcm = np.frombuffer(wf.readframes(wf.getnframes()), np.int16).astype(np.float32) / 32768.0
        sr = wf.getframerate(); wf.close()
        assert sr == 16000
    except Exception as exc:
        raise RuntimeError('audio.wav 必须是有效的 16k PCM 音频，不能跳过声学检查') from exc
    win, hop = 320, 160          # 20ms 窗 / 10ms 步
    c = np.concatenate(([0.0], np.cumsum(pcm * pcm)))
    fl = np.concatenate(([0], np.cumsum((pcm[:-1] * pcm[1:] < 0).astype(np.int32))))
    n = max(0, (len(pcm) - win) // hop)
    idx = np.arange(n) * hop
    rmsA = np.sqrt((c[idx + win] - c[idx]) / win)
    zcrA = (fl[idx + win - 1] - fl[idx]) / win
    def rms(t):
        i = int(t * 100)
        return float(rmsA[min(max(i, 0), n - 1)]) if n else 0.0
    def zcr(t):
        i = int(t * 100)
        return float(zcrA[min(max(i, 0), n - 1)]) if n else 1.0
    return rms, zcr
RMS_F, ZCR_F = _load_acoustic()

WORDS = [w for s in W for w in s.get('words', [])]
LEAD, TAIL = 0.25, 0.30
WIDE = ("[0:v]crop=960:488:0:122,scale=1280:-2:flags=lanczos,unsharp=5:5:0.35:5:5:0.0[m];"
        "[0:v]crop=320:180:960:270,scale=256:-2:flags=lanczos[pp];[m][pp]overlay=W-w-14:H-h-14[v]")
# 0915: 垫边=重度压暗模糊（防内容里的人脸在边里出模糊分身=同人双头像硬事故）
WIDE_PUSH_NOPIP = ("[0:v]crop=960:488:0:122,scale=1280:650:flags=lanczos,unsharp=5:5:0.35:5:5:0.0[c];"
        "[c]split[ca][cb];[ca]scale=1362:692,boxblur=28,eq=brightness=-0.45:saturation=0.3[bg];[bg][cb]overlay=41:21[pz];"
        "[pz]zoompan=z='{Z0}+{DZ}*(pow(clip(({LO}+on/24)/{TT},0,1),2)*(3-2*clip(({LO}+on/24)/{TT},0,1)))'"
        ":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=1280x650:fps=24[v]")
# 0913 缓推：整片一条连续 push（94%→100%），LO=片内该 piece 的全局起始秒，TT=成片总秒
# 0915: PIP 移到 zoompan 之后贴——小窗恒定大小位置，且垫边（仅内容）不含人脸分身
WIDE_PUSH = ("[0:v]crop=960:488:0:122,scale=1280:650:flags=lanczos,unsharp=5:5:0.35:5:5:0.0[c];"
        "[c]split[ca][cb];[ca]scale=1362:692,boxblur=28,eq=brightness=-0.45:saturation=0.3[bg];[bg][cb]overlay=41:21[pz];"
        "[pz]zoompan=z='{Z0}+{DZ}*(pow(clip(({LO}+on/24)/{TT},0,1),2)*(3-2*clip(({LO}+on/24)/{TT},0,1)))'"
        ":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=1280x650:fps=24[zp];"
        "[0:v]crop=320:180:960:270,scale=256:-2:flags=lanczos[pp];[zp][pp]overlay=W-w-14:H-h-14[v]")
# 纯摄像头布局（讲者停止共享屏幕时）：整帧就是人，不裁 960、不叠 PIP
CAM_WIDE = "[0:v]crop=1280:650:0:40,unsharp=5:5:0.3:5:5:0.0[v]"
CAM_PUSH = "[0:v]crop=1120:568:80:76,scale=1280:650:flags=lanczos[v]"
PERSON = ("[0:v]crop=960:488:0:122,scale=1280:-2:flags=lanczos,eq=brightness=-0.14:saturation=0.65[bg];"
          "[0:v]crop=320:180:960:270,scale=520:-2:flags=lanczos[pf];[bg][pf]overlay=(W-w)/2:(H-h)/2-40[v]")

def word_bounds(t, kind):
    if kind == 'in':
        i = next(i for i, w in enumerate(WORDS) if w['start'] >= t - 0.05)
        w = WORDS[i]; prev = WORDS[i-1]['end'] if i else 0.0; gap = w['start'] - prev
        return (max(prev + min(0.08, gap/3), w['start'] - LEAD) if gap > 0.15 else w['start'] - 0.06), f"gap {gap:.2f}s before '{w['word'].strip()}'"
    i = next(i for i in range(len(WORDS)-1, -1, -1) if WORDS[i]['end'] <= t + 0.05)
    w = WORDS[i]; nxt = WORDS[i+1]['start'] if i+1 < len(WORDS) else w['end']+5; gap = nxt - w['end']
    return (min(nxt - min(0.08, gap/3), w['end'] + TAIL) if gap > 0.15 else w['end'] + 0.06), f"gap {gap:.2f}s after '{w['word'].strip()}'"

def integrity(a, b, wa, wb):
    bad = []
    for w in WORDS:
        wanted = w['start'] >= wa - 0.05 and w['end'] <= wb + 0.05
        if w['start'] < a < w['end'] and (w['end'] - a) > 0.10 and wanted: bad.append('CHOP-IN:' + w['word'])
        if w['start'] < b < w['end'] and (b - w['start']) > 0.10 and wanted: bad.append('CHOP-OUT:' + w['word'])
        if wanted and (w['end'] > b + 0.05 or w['start'] < a - 0.05): bad.append('DROPPED:' + w['word'])
    return bad

def text_between(a, b):
    return ' '.join(s['text'].strip() for s in W if s['start'] >= a-0.4 and s['end'] <= b+0.4)

def render(spans, plan, tag, pip=True, seg_bounds=None, seg_options=None):
    d = f'build/{tag}'; os.makedirs(d, exist_ok=True)
    CLIP_TT = round(sum(b - a for a, b in spans), 3)
    seg_bounds = seg_bounds or [(0.0, CLIP_TT, 'in')]   # 0915: 每观点段一个镜头；motion: in推近/out拉远/hold稳住
    MZ = {'in': (1.0, 0.0644), 'out': (1.0644, -0.0644), 'hold': (1.0644, 0.0)}
    def seg_of(t):
        for sb in seg_bounds:
            if sb[0] - 1e-6 <= t < sb[1] + 1e-6: return sb
        return seg_bounds[-1]
    files = []; idx = 0
    for sh in plan:
        acc = 0.0; pieces = []
        for a, b in spans:
            s0, s1 = acc, acc + (b - a); acc = s1
            lo, hi = max(s0, sh['a']), min(s1, sh['b'])
            if hi - lo <= 0.02: continue
            pieces.append((a + (lo - s0), a + (hi - s0), lo))
        for sa, sb, plo in pieces:
            p = f'{d}/p{idx:03d}.mov'; idx += 1
            opts = next((opts for a, b, opts in (seg_options or []) if a - 1e-6 <= plo < b - 1e-6), {})
            mode = {'screen': 'W', 'camera': 'CAM'}.get(opts.get('layout'), sh['mode'])
            if mode == 'CAM': vf = CAM_WIDE
            elif mode == 'CAMF': vf = CAM_PUSH
            elif mode in ('W', 'F'):
                sgb = seg_of(plo); s0, s1 = sgb[0], sgb[1]
                z0, dz = MZ.get(sgb[2] if len(sgb) > 2 else 'in', MZ['in'])
                vf = (WIDE_PUSH if opts.get('pip', pip) else WIDE_PUSH_NOPIP).format(LO=round(plo - s0, 3), TT=max(round(s1 - s0, 3), 3.0), Z0=z0, DZ=dz)
            elif mode == 'P': vf = PERSON
            else: raise ValueError(f'未知画面模式: {mode}')
            for key, default in [('screen_rect', '960:488:0:122'), ('pip_rect', '320:180:960:270')]:
                if key in opts:
                    x, y, w, h = opts[key]
                    if min(x, y) < 0 or min(w, h) <= 0: raise ValueError(f'非法 {key}')
                    vf = vf.replace('crop=' + default, f'crop={w}:{h}:{x}:{y}')
            subprocess.run(['ffmpeg','-v','error','-ss',str(sa),'-to',str(sb),'-i',SRC,
                '-filter_complex',vf,'-map','[v]','-map','0:a',
                '-af','afade=t=in:st=0:d=0.012,areverse,afade=t=in:st=0:d=0.012,areverse',
                '-c:v','libx264','-preset','veryfast','-qp','0','-pix_fmt','yuv420p','-r','24',
                '-c:a','pcm_s16le','-ar','48000','-ac','2','-video_track_timescale','24000',p,'-y'], check=True)
            files.append(os.path.basename(p))
    open(f'{d}/concat.txt','w').write('\n'.join(f"file '{f}'" for f in files))
    base = f'{tag}_base.mov'
    subprocess.run(['ffmpeg','-v','error','-f','concat','-safe','0','-i',f'{d}/concat.txt','-c','copy','-movflags','+faststart',base,'-y'], check=True)
    return base

def plan_shots(spans, total, labels, modes=None, layout='screen'):
    """阶梯机位：W → F(推近，整段不动) → P(人像收口)。边界吸到 span 边界，每机位 ≥6s。"""
    acc = 0.0; ends = [0.0]
    for a, b in spans: acc += b - a; ends.append(acc)
    def snap(t): return min(ends, key=lambda x: abs(x - t))
    b1, b2 = snap(total * 0.28), snap(total * 0.72)
    cand = sorted({0.0, b1, b2, total})
    # 保证每段 >=6s，不满足就并掉
    merged = [cand[0]]
    for x in cand[1:]:
        if x - merged[-1] >= 6.0: merged.append(x)
    if merged[-1] < total - 1e-6:
        if total - merged[-1] >= 6.0: merged.append(total)
        else: merged[-1] = total
    default = ['CAM','CAMF','CAM'] if layout == 'camera' else ['W','W','W']
    modes = (modes or default)[:len(merged)-1] or [default[0]]
    def to_src(o):
        a2 = 0.0
        for a, b in spans:
            if o <= a2 + (b - a) + 1e-6: return a + (o - a2)
            a2 += b - a
        return spans[-1][1]
    plan = []
    for i in range(len(merged)-1):
        a, b = merged[i], merged[i+1]
        mode = modes[i] if i < len(modes) else 'W'
        crop = None
        if mode == 'CAMF':
            plan.append(dict(a=a, b=b, mode=mode, crop=None, labels=[(a, labels[i] if i < len(labels) else None)]))
            continue
        if mode == 'F':
            mode = 'W'   # F 机位已废除（0906 负责人拍板：高亮绿框不可存在），共享屏恒为 内容+PIP 人脸
        labs = [(a, labels[i] if i < len(labels) else None)]
        plan.append(dict(a=a, b=b, mode=mode, crop=crop, labels=labs))
    return plan

spec = json.load(open(os.environ.get('SPEC','spec.json')))
ONLY = os.environ.get('ONLY')
if ONLY:
    spec = [c for c in spec if c['slug'] == ONLY]
    if not spec: sys.exit(f'ONLY={ONLY} 不在 spec')

report = []
for clip in spec:
    segs = []
    for s in clip['segs']:
        a, ra = word_bounds(s['a'], 'in'); b, rb = word_bounds(s['b'], 'out')
        options = {k: s.get(k, clip.get(k)) for k in ('layout', 'pip', 'pip_rect', 'screen_rect') if s.get(k, clip.get(k)) is not None}
        if options.get('layout') not in (None, 'screen', 'camera'): raise ValueError('layout 必须为 screen 或 camera')
        segs.append(dict(title=s['title'], why=s['why'], options=options, motion=s.get('motion','in'), label=s.get('label'), cut_a=round(a,2), cut_b=round(b,2), dur=round(b-a,2),
                         snap_a=ra, snap_b=rb, bad=integrity(a,b,s['a'],s['b']), text=text_between(s['a'], s['b'])))
    spans = []; drop = 0; sq = 0.0
    for sg in segs:
        sg['lwords'] = [w for w in WORDS if w['end'] >= sg['cut_a'] - 1.2 and w['start'] <= sg['cut_b'] + 1.2]
        sp, st = smooth_build(WORDS, sg['cut_a'], sg['cut_b'], rms=RMS_F, zcr=ZCR_F)
        # One edit timeline for video, audio and subtitles: cuts must land on frames.
        sp = [(round(a * 24) / 24, round(b * 24) / 24) for a, b in sp]
        sp = [(a, b) for a, b in sp if b > a]
        sg['spans'] = sp; spans += sp; drop += st['dropped']; sq = round(sq + st['squeezed'], 2)
    total = sum(b-a for a, b in spans)
    import layoutdet
    def to_src_top(o):
        a2 = 0.0
        for a, b in spans:
            if o <= a2 + (b - a) + 1e-6: return a + (o - a2)
            a2 += b - a
        return spans[-1][1]
    probes = [layoutdet.mode_at(to_src_top(total * f))[0] for f in (0.15, 0.5, 0.85)]
    layout = clip.get('layout_force') or ('camera' if probes.count('camera') >= 2 else 'screen')  # 暗窗骗探测器时以人眼核帧的 layout_force 为准
    clip['layout'] = layout; clip['layout_probes'] = probes
    plan = plan_shots(spans, total, clip.get('labels',[None,None,None]), clip.get('shot_modes'), layout)
    seg_bounds = []; acc2 = 0.0
    for sg in segs:
        d2 = sum(b - a for a, b in sg['spans'])
        seg_bounds.append((round(acc2, 3), round(acc2 + d2, 3), sg.get('motion', 'in'))); acc2 += d2
    clip['seg_bounds'] = seg_bounds
    clip['seg_labels'] = [[sb[0], sb[1], sg.get('label')] for sb, sg in zip(seg_bounds, segs) if sg.get('label')]
    seg_options = [(sb[0], sb[1], sg['options']) for sb, sg in zip(seg_bounds, segs)]
    base = render(spans, plan, clip['slug'], pip=clip.get('pip', True), seg_bounds=seg_bounds, seg_options=seg_options)
    bad = [x for sg in segs for x in sg['bad']]
    clip.update(segs=segs, spans=spans, shots=plan, raw=round(sum(s['dur'] for s in segs),1),
                smoothed=round(total,1), dropped=drop, squeezed=sq,
                integrity='PASS' if not bad else bad, base=base)
    report.append(clip)
    print(f"[{clip['slug']}] {clip['raw']}s -> {total:.1f}s | 布局 {layout} | 片段{len(spans)} | 删口头禅{drop} | 压气口{sq}s | 机位{[p['mode'] for p in plan]} | 完整性 {'PASS' if not bad else bad}")
outp = os.environ.get('OUT','built.json')
if ONLY and os.path.exists(outp):   # 窄重跑：只替换本 slug，其余条目原样保留
    new = {c['slug']: c for c in report}
    old = json.load(open(outp))
    report = [new.pop(c['slug'], c) for c in old] + list(new.values())
json.dump(report, open(outp,'w'), ensure_ascii=False, indent=1)
