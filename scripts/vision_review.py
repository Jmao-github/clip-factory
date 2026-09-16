#!/usr/bin/env python3
"""G6 成片视觉审查（负责人 0906 拍板的新机制）：
每条成片按 ≤2.5s 间隔全程抽帧 → 拼 3×2 网格 → Gemini 逐格严判 artifact。
本脚本只产出网格与 Gemini 意见（vision_gemini.json）；最终 final_vision_review.json
由主流程在「Gemini 意见 + 本人逐帧人眼确认」后写入。
Artifact 类别：悬空的框/线条、字幕与标签重叠、文字被裁半、人脸被裁坏、
黑边比例异常、PIP 缺失或位置错、UI 元素叠糊、任何看起来是渲染事故的东西。"""
import json, os, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # 兄弟模块按引擎目录解析，不看 cwd
from gvid import key
import base64, urllib.request

PROMPT = """这是一条短视频成片的连续抽帧网格（左上→右下按时间排列）。这条视频即将发布到社区。
你是毙稿官：逐格找**渲染事故**，包括但不限于：
- 画面上悬空的矩形框/线条/色块（不属于原始内容的）
- 字幕与其他文字元素重叠、字幕被裁、字幕超过两行
- 人脸被裁切到只剩一部分、人脸小窗(PIP)缺失或叠在内容关键区上
- 幻灯片/屏幕内容被裁掉关键部分（标题被切半等）
- 突兀的黑边、画面比例异常、内容拉伸变形
- 两层画面叠加穿帮
- **同一个人出现两个头像**（例如右下人脸小窗与画面内嵌的讲者自拍浮窗同框）——这是硬事故
- 头像/人脸被画面边缘裁掉一半
注意：底部居中的白字黑边字幕、左上角深底绿字标签卡是**设计内**元素，只有当它们重叠/裁切/位置错乱时才算事故。
逐格输出：格号 + OK 或 事故描述。最后一行输出 VERDICT: CLEAN 或 VERDICT: ARTIFACTS。"""

def ask_img(img_path):
    K = key()
    b64 = base64.b64encode(open(img_path,'rb').read()).decode()
    body = json.dumps({'contents':[{'parts':[{'inline_data':{'mime_type':'image/jpeg','data':b64}},{'text':PROMPT}]}],
                       'generationConfig':{'temperature':0.1,'maxOutputTokens':8192}}).encode()
    url = f'https://generativelanguage.googleapis.com/v1beta/models/gemini-3-flash-preview:generateContent?key={K}'
    import time, urllib.error
    for a in range(5):
        try:
            r = urllib.request.Request(url, data=body, headers={'Content-Type':'application/json'})
            with urllib.request.urlopen(r, timeout=300) as f: d = json.load(f)
            return ''.join(p.get('text','') for p in d['candidates'][0]['content']['parts'])
        except urllib.error.HTTPError as e:
            if e.code not in (503,429): raise
            time.sleep(8*(a+1))
    raise SystemExit('gemini gave up')

res = []
ONLY = os.environ.get('ONLY')
os.makedirs('vrev', exist_ok=True)
for c in json.load(open('built.json')):
    if ONLY and c['slug'] != ONLY: continue
    f = c['file']
    dur = float(subprocess.run(['ffprobe','-v','error','-show_entries','format=duration','-of','csv=p=0',f],
                               capture_output=True,text=True).stdout)
    step = 2.5
    ts = [round(i*step,2) for i in range(int(dur/step)+1)]
    frames = []
    for i,t in enumerate(ts):
        p = f"vrev/{c['slug']}_{i:03d}.jpg"
        subprocess.run(['ffmpeg','-v','error','-ss',str(t),'-i',f,'-frames:v','1','-q:v','4','-vf','scale=640:-2',p,'-y'],check=True)
        frames.append(p)
    grids = []
    for g in range(0, len(frames), 6):
        chunk = frames[g:g+6]
        gp = f"vrev/{c['slug']}_grid{g//6}.jpg"
        ins = []; fc = []
        for j,fp in enumerate(chunk): ins += ['-i', fp]
        layout = '|'.join(['0_0','w0_0','w0+w1_0','0_h0','w0_h0','w0+w1_h0'][:len(chunk)])
        if len(chunk) == 1:
            subprocess.run(['ffmpeg','-v','error','-i',chunk[0],gp,'-y'],check=True)
        else:
            subprocess.run(['ffmpeg','-v','error']+ins+['-filter_complex',
                f"{''.join(f'[{k}]' for k in range(len(chunk)))}xstack=inputs={len(chunk)}:layout={layout}:fill=black",gp,'-y'],check=True)
        grids.append(gp)
    verdicts = []
    for gp in grids:
        out = ask_img(gp)
        verdicts.append(dict(grid=gp, review=out, clean='VERDICT: CLEAN' in out))
        print(f"{c['slug']} {gp}: {'CLEAN' if 'VERDICT: CLEAN' in out else 'ARTIFACTS'}")
    res.append(dict(slug=c['slug'], file=f, frames=len(frames), grids=[v for v in verdicts]))
if ONLY and os.path.exists('vision_gemini.json'):   # 窄重跑：合并不覆盖
    new = {r['slug']: r for r in res}
    res = [new.pop(r['slug'], r) for r in json.load(open('vision_gemini.json'))] + list(new.values())
json.dump(res, open('vision_gemini.json','w'), ensure_ascii=False, indent=1)
bad = [v for r in res for v in r['grids'] if not v['clean']]
print(f"GRIDS: {sum(len(r['grids']) for r in res)}, ARTIFACT-GRIDS: {len(bad)}")
