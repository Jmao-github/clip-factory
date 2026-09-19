#!/usr/bin/env python3
"""G13 口头禅终检（v9，0918 立）——发布前用**独立于 whisper 的转写器**复听成片。

为什么必须独立：G2 重转写 gate 是拿 whisper 的转写去比 whisper 的重转写，两边是同一个
模型、同一套盲区，对口头禅**结构上不可能报错**——它只证明模型自洽，不证明模型正确。
实测：五条已过全部 12 道 gate 的成片里，有两条各残留 10 个和 6 个 uh，没有任何一道查得出来。

判据：成片里独立的 uh/um/er 数量必须为 0。
计费：每条 ≈10 credits（两家都是这个量级），一场 5 条约 50。

用法：
  WORKDIR=<dir> python3 filler_gate.py            # 查 built.json 里全部 clip
  WORKDIR=<dir> ONLY=<slug> python3 filler_gate.py
  VENDOR=opus|descript 选后端（默认 opus，它还额外给词级时间戳）
输出 filler_gate.json + 末行 FILLER-CLEAN / FILLER-FAIL（FAIL 时退出码非零）。
"""
import json, os, subprocess, sys

ENGINE = os.path.dirname(os.path.abspath(__file__))
os.chdir(os.environ.get('WORKDIR', '.'))
ONLY = os.environ.get('ONLY')
VENDOR = os.environ.get('VENDOR', 'opus')
OUT = 'filler_gate.json'

clips = json.load(open(os.environ.get('BUILT', 'built.json')))
prev = {r['slug']: r for r in (json.load(open(OUT)) if os.path.exists(OUT) else [])}
res, ok = [], True

for c in clips:
    slug = c['slug']
    if ONLY and slug != ONLY:
        if slug in prev:
            res.append(prev[slug])          # 窄重跑：其余条目原样保留
        continue
    film = c.get('file') if os.path.exists(c.get('file', '')) else slug + '.mp4'
    if not os.path.exists(film):
        print(f'{slug:30} 找不到成片 {film}')
        res.append(dict(slug=slug, ok=False, error='film missing')); ok = False
        continue
    tmp = f'_fg_{slug}.json'
    r = subprocess.run([sys.executable, os.path.join(ENGINE, 'faithful_transcript.py')],
                       env=dict(os.environ, SRC=os.path.abspath(film), OUT=tmp, VENDOR=VENDOR,
                                TITLE=f'filler-gate {slug}'),
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(f'{slug:30} 转写失败: {(r.stderr or r.stdout)[-300:]}')
        res.append(dict(slug=slug, ok=False, error='transcript failed')); ok = False
        continue
    d = json.load(open(tmp))
    f = d['fillers']
    good = len(f) == 0
    ok &= good
    res.append(dict(slug=slug, vendor=d['vendor'], words=len(d['words']),
                    fillers=len(f), spots=[[w['start'], w['w']] for w in f][:40], ok=good))
    print(f"{slug:30} 口头禅 {len(f):3}  {'OK' if good else 'FAIL'}  "
          f"{[round(w['start'],1) for w in f][:10]}")

json.dump(res, open(OUT, 'w'), ensure_ascii=False, indent=1)
print('FILLER-CLEAN' if ok else 'FILLER-FAIL')
sys.exit(0 if ok else 1)
