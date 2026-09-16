#!/usr/bin/env python3
"""gvid — 让 Gemini 看视频并按 prompt 出结构化评审。
用法: python3 gvid.py <video.mp4> <prompt-file-or-string> [--model gemini-3.1-pro-preview]
"""
import json, os, sys, time, mimetypes, urllib.request, urllib.error
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from envkey import get_key

def key():
    return get_key('GEMINI_VIDEO_API_KEY', 'GEMINI_API_KEY')

BASE = 'https://generativelanguage.googleapis.com'

def req(url, data=None, headers=None, method=None):
    r = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(r, timeout=600) as f:
            return f.read(), dict(f.headers)
    except urllib.error.HTTPError as e:
        raise SystemExit(f'HTTP {e.code}: {e.read()[:800].decode()}')

def upload(path, K):
    sz = os.path.getsize(path)
    mime = mimetypes.guess_type(path)[0] or 'video/mp4'
    _, h = req(f'{BASE}/upload/v1beta/files?key={K}',
               data=json.dumps({'file': {'display_name': os.path.basename(path)}}).encode(),
               headers={'X-Goog-Upload-Protocol': 'resumable', 'X-Goog-Upload-Command': 'start',
                        'X-Goog-Upload-Header-Content-Length': str(sz),
                        'X-Goog-Upload-Header-Content-Type': mime, 'Content-Type': 'application/json'})
    up = h.get('X-Goog-Upload-URL') or h.get('x-goog-upload-url')
    body, _ = req(up, data=open(path, 'rb').read(),
                  headers={'Content-Length': str(sz), 'X-Goog-Upload-Offset': '0',
                           'X-Goog-Upload-Command': 'upload, finalize'})
    f = json.loads(body)['file']
    while f['state'] == 'PROCESSING':
        time.sleep(4)
        f = json.loads(req(f"{BASE}/v1beta/{f['name']}?key={K}")[0])
    if f['state'] != 'ACTIVE':
        raise SystemExit('upload failed: ' + f['state'])
    return f

def ask(path, prompt, model='gemini-3.1-pro-preview'):
    K = key()
    f = upload(path, K)
    payload = {'contents': [{'parts': [{'file_data': {'mime_type': f['mimeType'], 'file_uri': f['uri']}},
                                       {'text': prompt}]}],
               'generationConfig': {'temperature': 0.3, 'maxOutputTokens': 8192}}
    last = None
    for attempt in range(6):
        try:
            body, _ = req(f'{BASE}/v1beta/models/{model}:generateContent?key={K}',
                          data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
            break
        except SystemExit as e:
            last = str(e)
            if '503' not in last and '429' not in last: raise
            time.sleep(8 * (attempt + 1))
    else:
        raise SystemExit('gave up after retries: ' + str(last))
    d = json.loads(body)
    try:
        return ''.join(p.get('text', '') for p in d['candidates'][0]['content']['parts'])
    except Exception:
        return json.dumps(d)[:2000]

if __name__ == '__main__':
    v, p = sys.argv[1], sys.argv[2]
    if os.path.exists(p): p = open(p).read()
    model = sys.argv[sys.argv.index('--model') + 1] if '--model' in sys.argv else 'gemini-3.1-pro-preview'
    print(ask(v, p, model))
