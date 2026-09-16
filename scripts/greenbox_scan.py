#!/usr/bin/env python3
"""G4 绿框根除机检：
1) overlay.py 里不得再有高亮框绘制代码（rounded_rectangle + outline 绿色签名）
2) 三条成片全程 2fps 抽帧，绿框色 (120,230,160)±28 像素计数；
   标签卡绿字 ≲4000px，框轮廓 ≳15000px → 阈值 8000 判 FAIL。
输出最后一行 GREENBOX-CLEAN 或 GREENBOX-FAIL。"""
import json, subprocess, sys
import numpy as np

ok = True
src = open('overlay.py').read()
if 'outline=(120,230,160' in src.replace(' ', ''):
    print('overlay.py 仍含高亮框绘制代码'); ok = False

# promote 后 cand 已转正 → 回退到正式片名；扫不到帧=空转，必须硬失败（0915晚：曾对已转正片静默扫 0 帧假过）
import os
clips = [c['file'] if os.path.exists(c['file']) else c['slug'] + '.mp4'
         for c in json.load(open('built.json'))]
W, H = 1280, 650
for f in clips:
    p = subprocess.Popen(['ffmpeg','-v','error','-i',f,'-vf','fps=2','-f','rawvideo','-pix_fmt','rgb24','-'],
                         stdout=subprocess.PIPE)
    n = 0; worst = 0
    while True:
        buf = p.stdout.read(W*H*3)
        if len(buf) < W*H*3: break
        a = np.frombuffer(buf, np.uint8).reshape(H, W, 3).astype(np.int16)
        m = (abs(a[:,:,0]-120)<28) & (abs(a[:,:,1]-230)<28) & (abs(a[:,:,2]-160)<28)
        cnt = int(m.sum()); worst = max(worst, cnt)
        if cnt > 8000:
            print(f'{f} frame#{n} 绿框色像素 {cnt} > 8000'); ok = False
        n += 1
    p.wait()
    if n == 0:
        print(f'{f}: 0 帧扫描——文件缺失或不可解码，拒绝空转放行'); ok = False
    print(f'{f}: {n} 帧扫描, 最大绿色像素 {worst}')
print('GREENBOX-CLEAN' if ok else 'GREENBOX-FAIL')
