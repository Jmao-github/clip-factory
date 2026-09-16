#!/usr/bin/env python3
"""图文一致性机检：一帧画面 × 该时段口播 → Gemini 判 MATCH / MISMATCH。
用法: python3 avcheck.py <frame.png|jpg> "<spoken text>"
输出最后一行: AV:MATCH 或 AV:MISMATCH，倒数第二行是理由。"""
import base64, json, os, sys, time, urllib.request, urllib.error
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from envkey import get_key

def key():
    return get_key('GEMINI_VIDEO_API_KEY', 'GEMINI_API_KEY')

def ask(img_path, spoken, model='gemini-3-flash-preview'):
    K = key()
    mime = 'image/png' if img_path.endswith('.png') else 'image/jpeg'
    b64 = base64.b64encode(open(img_path,'rb').read()).decode()
    prompt = f"""这是一条讲解视频中某一时刻的画面截图。此刻讲者正在说：

"{spoken}"

分两步回答：

第一步：画面的**主体**是什么？如果画面上有明确的产品名/项目名/页面标题，把它写出来。

第二步：口播在讨论的**对象**是什么？

判定规则（严格执行）：
- 画面主体**就是**口播讨论的对象，或是它的示意图/演示/相关界面 → MATCH
- 画面是中性内容（讲者摄像头、空白桌面、无具体主题）→ MATCH
- 画面主体是一个**具体命名的产品/项目/页面**，而口播讨论的是**另一件事**（哪怕两者同属一个大领域）→ MISMATCH。
  例：口播讲"我不用再切分支了"（讲的是 Cursor 工作流），画面却是另一个工具的 GitHub README → MISMATCH。
  "都是开发者工具"不构成 MATCH，主体必须对上。

最后一行只输出 MATCH 或 MISMATCH。"""
    body = json.dumps({'contents':[{'parts':[{'inline_data':{'mime_type':mime,'data':b64}},{'text':prompt}]}],
                       'generationConfig':{'temperature':0.1,'maxOutputTokens':8192}}).encode()
    url = f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={K}'
    last=None
    for a in range(6):
        try:
            with urllib.request.urlopen(urllib.request.Request(url,data=body,headers={'Content-Type':'application/json'}),timeout=300) as f:
                d=json.load(f)
            return ''.join(p.get('text','') for p in d['candidates'][0]['content']['parts'])
        except urllib.error.HTTPError as e:
            last=f'{e.code}'
            if e.code not in (503,429): raise SystemExit(f'{e.code}: {e.read()[:200].decode()}')
            time.sleep(8*(a+1))
    raise SystemExit('gave up: '+str(last))

if __name__=='__main__':
    out = ask(sys.argv[1], sys.argv[2])
    lines=[l.strip() for l in out.strip().split('\n') if l.strip()]
    verdict = 'MATCH' if lines[-1].upper().endswith('MATCH') and not lines[-1].upper().endswith('MISMATCH') else 'MISMATCH'
    print('\n'.join(lines[:-1]))
    print('AV:'+verdict)
