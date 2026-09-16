#!/usr/bin/env python3
"""Gemini 纯文本调用（带 503 退避重试）。"""
import json, os, sys, time, urllib.request, urllib.error
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from envkey import get_key
def key():
    return get_key('GEMINI_VIDEO_API_KEY', 'GEMINI_API_KEY')
def ask(prompt, model='gemini-3-flash-preview', maxtok=32768):
    K=key(); url=f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={K}'
    body=json.dumps({'contents':[{'parts':[{'text':prompt}]}],
                     'generationConfig':{'temperature':0.2,'maxOutputTokens':maxtok}}).encode()
    last=None
    for a in range(6):
        try:
            r=urllib.request.Request(url,data=body,headers={'Content-Type':'application/json'})
            with urllib.request.urlopen(r,timeout=600) as f: d=json.load(f)
            return ''.join(p.get('text','') for p in d['candidates'][0]['content']['parts'])
        except urllib.error.HTTPError as e:
            last=f'{e.code}: {e.read()[:300].decode()}'
            if e.code not in (503,429): raise SystemExit(last)
            time.sleep(8*(a+1))
    raise SystemExit('gave up: '+str(last))
if __name__=='__main__':
    p=sys.argv[1]
    print(ask(open(p).read() if os.path.exists(p) else p))
