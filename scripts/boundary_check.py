#!/usr/bin/env python3
"""G11 边界词机检（0915 晚，源自负责人抓的「super perfect 的 perfect 被切没」+「接口处残留 uh」）：
对每条成片的每个接口（观点段边界 + 片头 + 片尾），重转写成片音频 ±2.5s 窗口，验证：
1. 上一段的最后一个实词在窗口转写里出现（词被读完才切）
2. 下一段的第一个实词在窗口转写里出现（开头没被吃）
3. 接口 ±0.45s 内无独立 uh/um（无残留口头禅导致的卡顿）
输出 boundary_check.json + 最后一行 BOUNDARY-PASS / BOUNDARY-FAIL。
支持 ONLY=<slug> 窄跑合并写回；BUILT env 换输入表。
"""
import difflib, json, os, re, subprocess
os.chdir(os.environ.get('WORKDIR', '.'))
import mlx_whisper

FILLER = re.compile(r"^(uh|um|erm|mm|hmm|mhm)$", re.I)
def norm(w): return re.sub(r"[^a-z0-9']", '', w.lower())

def transcribe_window(f, t0, t1):
    subprocess.run(['ffmpeg','-v','error','-ss',str(max(t0,0)),'-to',str(t1),'-i',f,
                    '-vn','-ac','1','-ar','16000','_bc.wav','-y'], check=True)
    # 0918：whisper 默认设置对口头禅是半聋的——同一段音频默认听出 0 个、加这句逐字提示词听出 4 个
    # （商用转写器听出 10 个）。本 gate 的 clip_fillers 全片扫描此前就是这样漏掉 16 个 uh 的。
    # 提示词是免费的部分补救；真相源仍以 G13 filler_gate（独立转写器）为准。
    r = mlx_whisper.transcribe('_bc.wav', path_or_hf_repo='mlx-community/whisper-large-v3-turbo',
                               word_timestamps=True, language='en',
                               initial_prompt='Verbatim transcript including every filler and '
                                              'hesitation: uh, um, er, you know, like.')
    return [dict(word=w['word'], start=w['start']+max(t0,0), end=w['end']+max(t0,0))
            for s in r['segments'] for w in s.get('words',[])]

def has_word(words, target, lo=None, hi=None):
    t = norm(target)
    if not t: return True
    for w in words:
        if lo is not None and w['end'] < lo: continue
        if hi is not None and w['start'] > hi: continue
        if difflib.SequenceMatcher(None, norm(w['word']), t).ratio() >= 0.75: return True
    return False

ONLY = os.environ.get('ONLY')
res = []
ok_all = True
for c in json.load(open(os.environ.get('BUILT','built.json'))):
    if ONLY and c['slug'] != ONLY: continue
    f = c['slug'] + '.cand.mp4'
    if not os.path.exists(f): f = c['slug'] + '.mp4'
    # 每观点段在成片时间轴里的首尾实词（从 lwords∩spans 取）
    seg_marks = []
    for sg, _sb in zip(c['segs'], c['seg_bounds']):
        s0, s1 = _sb[0], _sb[1]   # seg_bounds 自 v5 起带 motion 第三元
        sp = [tuple(x) for x in sg['spans']]
        kept = [w for w in sg.get('lwords', [])
                if not FILLER.match(norm(w['word'])) and any(a-0.05 <= w['start'] and w['end'] <= b+0.05 for a, b in sp)]
        if not kept: continue
        seg_marks.append(dict(s0=s0, s1=s1, first=kept[0]['word'].strip(), last=kept[-1]['word'].strip()))
    # 防空转护栏：built.json 没带 lwords（build.py 版本漂移，跨session合并丢过）→ 响亮 FAIL 而非零检查假过
    if c['segs'] and not seg_marks:
        ok_all = False
        res.append(dict(slug=c['slug'], checks=[], clip_fillers=[], ok=False,
                        error='lwords 缺失/为空——build.py 未输出词表契约，G11 无法检查（重跑 build.py 而非放行）'))
        print(f"{c['slug']:32} FAIL: lwords 缺失(build.py 版本漂移?)，G11 拒绝空转放行")
        continue
    checks = []
    for i, m in enumerate(seg_marks):
        # 片头：首词在开头 3s 内出现；接口/片尾：末词在边界前窗口出现
        for kind, t, target in (('first', m['s0'], m['first']), ('last', m['s1'], m['last'])):
            lo, hi = max(t-2.5, 0), t+2.5
            words = transcribe_window(f, lo, hi)
            good = has_word(words, target, lo=t-2.6 if kind=='last' else None, hi=None if kind=='last' else t+2.6)
            fillers = [w for w in words if FILLER.match(norm(w['word'])) and abs((w['start']+w['end'])/2 - t) <= 0.45]
            checks.append(dict(seg=i, kind=kind, t=round(t,2), target=target, found=good,
                               junction_fillers=[x['word'].strip() for x in fillers]))
            if not good or fillers: ok_all = False
    # 0915晚·负责人拍板「口头禅强制去掉，一个都不能有」：整条成片机器重听，
    # 出现任何可转写出的 uh/um（含被删后留下的残响被听成 uh）→ 直接 FAIL 并给出时间码
    dur = float(subprocess.run(['ffprobe','-v','error','-show_entries','format=duration','-of','csv=p=0',f],
                               capture_output=True,text=True).stdout)
    fullw = transcribe_window(f, 0.0, dur)
    clip_fillers = [dict(t=round(w['start'],2), w=w['word'].strip()) for w in fullw if FILLER.match(norm(w['word']))]
    if clip_fillers: ok_all = False
    res.append(dict(slug=c['slug'], checks=checks, clip_fillers=clip_fillers,
                    ok=all(x['found'] and not x['junction_fillers'] for x in checks) and not clip_fillers))
    bad = [x for x in checks if not x['found'] or x['junction_fillers']]
    detail = '; '.join("seg{}/{} '{}' found={} fillers={}".format(x['seg'], x['kind'], x['target'], x['found'], x['junction_fillers']) for x in bad)
    fdetail = ' | 全片可听口头禅: ' + ', '.join(f"{x['w']}@{x['t']}s" for x in clip_fillers) if clip_fillers else ''
    print(f"{c['slug']:32} {'OK' if not bad and not clip_fillers else 'FAIL: ' + detail + fdetail}")
if ONLY and os.path.exists('boundary_check.json'):
    new = {r['slug']: r for r in res}
    res = [new.pop(r['slug'], r) for r in json.load(open('boundary_check.json'))] + list(new.values())
json.dump(res, open('boundary_check.json','w'), ensure_ascii=False, indent=1)
ok = all(r['ok'] for r in res)
print('BOUNDARY-PASS' if ok else 'BOUNDARY-FAIL')
import sys; sys.exit(0 if ok else 1)
