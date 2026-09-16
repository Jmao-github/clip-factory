#!/usr/bin/env python3
"""G12 拼接点残响声学机检（0915 晚，负责人抓「clip2 4/6/9/12/14s 全是 uh」后立）：
whisper 对"被删 filler 留下的半截残响"是聋的（负向对照实测转写不出），
所以直接查波形：每个 keep-span 的 pre-roll 区（span 起点→首词起声点）应当是静音，
出现 ≥0.04s 持续发声（RMS≥阈值）= 残响 = FAIL，报出源时间码+成片时间码。
用法：WORKDIR=… python3 splice_audit.py [BUILT=built.json] [ONLY=slug]
输出 splice_audit.json + 最后一行 SPLICE-PASS / SPLICE-FAIL。
"""
import json, os, wave
import numpy as np
os.chdir(os.environ.get('WORKDIR', '.'))

TH = 0.012      # 与 smooth.VOICE_TH 一致
WIN = 0.02      # 20ms 窗
MIN_BLOB = 0.04 # ≥2 窗连续发声判残响

wf = wave.open('audio.wav', 'rb')
pcm = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
wf.close()
def rms(t):
    i = int(t * 16000)
    if i < 0 or i + 320 > len(pcm): return 0.0
    s = pcm[i:i+320]
    return float(np.sqrt((s*s).mean()))

def zcr(t):
    i = int(t * 16000)
    if i < 0 or i + 320 > len(pcm): return 0.0
    s = pcm[i:i+320]
    return float(np.mean(np.abs(np.diff(np.sign(s))))) / 2

import re
FILLER = re.compile(r"^\s*(uh|um|erm|mm|hmm|mhm)[,.?!…\-]*\s*$", re.I)
CONS_HEAD = 'sfzcxhptkbdgjqvw'

ONLY = os.environ.get('ONLY')
res = []
for c in json.load(open(os.environ.get('BUILT', 'built.json'))):
    if ONLY and c['slug'] != ONLY: continue
    viol = []
    off = 0.0
    for sg in c['segs']:
        lw = sg.get('lwords', [])
        if not lw:
            raise RuntimeError(f"{c['slug']}: 缺少词表，无法检查残响")
        for s, e in [tuple(x) for x in sg['spans']]:
            w0 = next((w for w in lw if w['start'] >= s - 0.35 and not FILLER.match(w['word']) and w['start'] < e), None)
            filler_adj = any(FILLER.match(w['word']) and s - 1.2 <= w['start'] <= (w0['start'] if w0 else s + 0.8)
                             for w in lw)
            # A) pre-roll 残响：从词头回扫真实起声点，起声点前的 pre-roll 里不得有 ≥0.04s 发声
            if w0:
                u = w0['start'] + 0.04
                while u > s + 0.005 and rms(u - 0.01) >= TH: u -= 0.01
                onset = u
                if onset > s + 0.03:
                    run = 0.0; blob = 0.0; t = s + 0.005
                    while t < onset - 0.01:
                        if rms(t) >= TH: run += WIN; blob = max(blob, run)
                        else: run = 0.0
                        t += WIN
                    if blob >= MIN_BLOB:
                        viol.append(dict(kind='residue', src=round(s, 2), clip=round(off, 2),
                                         blob=round(blob, 2), next_word=w0['word'].strip()))
            # B) 粘连 uh：删过 filler + 下一词辅音开头，但 span 开头第一段发声是 ≥0.10s 低ZCR元音
            if w0 and filler_adj and w0['word'].strip().strip('.,?!').lower()[:1] in CONS_HEAD:
                t = s
                while t < s + 0.8 and rms(t) < TH: t += 0.01
                # 0915晚修：真粘连=发声起点明显早于词标(uh 占前段)；起点≈词标±0.05=词自己的浊音词头
                # ('the'/ð/、'but'/b/ 案——首字母辅音表猜不准实际音值，codex 留档缺陷的闭环)
                head = 0.0; u = t
                if t >= w0['start'] - 0.05: u = t + 1e9   # 跳过判定

                while rms(u) >= TH and zcr(u) < 0.25 and head < 0.45:
                    u += 0.01; head += 0.01
                if head >= 0.10:
                    viol.append(dict(kind='glued-uh', src=round(s, 2), clip=round(off, 2),
                                     blob=round(head, 2), next_word=w0['word'].strip()))
            off += e - s
    res.append(dict(slug=c['slug'], violations=viol, ok=not viol))
    detail = '; '.join("{}@成片{}s(源{}s,{}s)→{}".format(v.get('kind', 'residue'), v['clip'], v['src'], v['blob'], v['next_word']) for v in viol)
    print(f"{c['slug']:32} {'OK' if not viol else 'FAIL: ' + detail}")
if ONLY and os.path.exists('splice_audit.json'):
    new = {r['slug']: r for r in res}
    res = [new.pop(r['slug'], r) for r in json.load(open('splice_audit.json'))] + list(new.values())
json.dump(res, open('splice_audit.json', 'w'), ensure_ascii=False, indent=1)
print('SPLICE-PASS' if all(r['ok'] for r in res) else 'SPLICE-FAIL')
