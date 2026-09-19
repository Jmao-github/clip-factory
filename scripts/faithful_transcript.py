#!/usr/bin/env python3
"""忠实转写（v9，0918 实测后立）——口头禅的真相源。

为什么需要它：本管线删口头禅的做法是「在词表里找 uh/um 然后删掉」，
所以**转写没写下来的口头禅，我们永远删不掉**。实测同一段 48 秒音频：
  whisper 默认设置      0 个
  whisper + 逐字提示词  4 个
  Descript             10 个
  OpusClip              6 个（另一条片，与 Descript 完全一致）
而且盲区不均匀——同一场里有的段落 whisper 老实写、有的一个不写，所以
「本段删了 0 个」从来不等于「本段干净」。详见 references/vendor-api-evaluation.md。

两条后端：
  VENDOR=opus      OpusClip GET /api/transcripts —— 词级时间戳 + 口头禅 + __silence 标记。
                   能同时用于「定位口头禅」和「当切点词表」。计费 1 credit/分钟，每项目最低 10。
  VENDOR=descript  Descript /export/transcript —— 忠实但只有句级 cue，够做 gate，不够做切点。
                   计费 ≈10 AI credits/条。

用法：
  VENDOR=opus SRC=path/to/video.mp4 OUT=faithful.json python3 faithful_transcript.py
输出 JSON：{vendor, source, duration, words[{w,start,end,filler}], fillers[...], silences[[a,b]]}
"""
import json, os, re, subprocess, sys, time, urllib.error, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from envkey import get_key

FILLER = re.compile(r"^(uh+|um+|er+|erm|mm+|hmm+)[.,!?;:\-]*$", re.I)
UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/140.0 Safari/537.36')


def _req(url, data=None, headers=None, method=None, timeout=300, raw=False):
    r = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    with urllib.request.urlopen(r, timeout=timeout) as f:
        b = f.read()
    if raw:
        return b
    return json.loads(b.decode() or '{}')


# ---------------------------------------------------------------- OpusClip
def opus(src):
    """上传 → 建项目 → 等 stage=COMPLETE → 取词级转写。"""
    key = get_key('OPUSCLIP_API_KEY')
    base = 'https://api.opus.pro/api'
    # Cloudflare 会用默认 UA 把请求挡掉（403 error code: 1010），必须伪装浏览器 UA
    H = {'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json',
         'Accept': 'application/json', 'User-Agent': UA}

    def api(path, body=None, method=None):
        return _req(base + path, json.dumps(body).encode() if body is not None else None,
                    H, method)

    buf = open(src, 'rb').read()
    size_mb = max(1, -(-len(buf) // 1048576))
    # /upload-links 没写进它公开的 OpenAPI，但本地文件必须走这条
    link = api('/upload-links', {'type': 'Upload', 'domain': 'Google', 'usecase': 'LocalUpload',
                                 'extension': 'mp4', 'fileName': os.path.basename(src),
                                 'size': size_mb})
    link = link.get('data', link)
    up_url = link.get('upload_url') or link.get('url')
    up_id = link.get('upload_id') or link.get('uploadId')
    init = urllib.request.urlopen(urllib.request.Request(
        up_url, data=b'', method='POST',
        headers={'x-goog-resumable': 'start', 'Content-Length': '0'}), timeout=120)
    session = init.headers['location']
    urllib.request.urlopen(urllib.request.Request(
        session, data=buf, method='PUT',
        headers={'Content-Type': 'application/octet-stream'}), timeout=1800)

    proj = api('/clip-projects', {
        'videoUrl': up_id,
        'uploadedVideoAttr': {'title': os.environ.get('TITLE', 'clip-factory faithful transcript')},
        # 只要转写，不要它剪辑结果；仍会按时长计费，最低 10 credits
        'curationPref': {'model': 'ClipAnything', 'clipDurations': [[20, 60]]},
        'renderPref': {'layoutAspectRatio': 'landscape'},
        'importPreference': {'sourceLang': os.environ.get('LANG_CODE', 'en')}})
    pid = proj['id']
    for _ in range(180):
        d = api(f'/clip-projects/{pid}')
        if d.get('stage') in ('COMPLETE', 'FAILED', 'ERROR'):   # 字段叫 stage 不叫 status
            break
        time.sleep(10)
    else:
        raise SystemExit('OpusClip 项目超时')

    tr = api(f'/transcripts?q=findByProjectId&projectId={pid}')
    data = tr.get('data')
    segs = data[0] if (isinstance(data, list) and data and isinstance(data[0], list)) else data
    words, silences = [], []
    for s in segs:
        for w in s.get('words', []):
            if w['word'] == '__silence':
                silences.append([round(w['start'], 3), round(w['end'], 3)])
                continue
            words.append(dict(w=w['word'], start=round(w['start'], 3), end=round(w['end'], 3),
                              filler=bool(FILLER.match(w['word'].strip()))))
    return dict(vendor='opus', project_id=pid, words=words, silences=silences)


# ---------------------------------------------------------------- Descript
def descript(src):
    """导入 → agent 转写 → 导出 srt。只有句级 cue，够做 gate，不够做切点。"""
    key = get_key('DESCRIPT_API_KEY')
    api_base = 'https://descriptapi.com/v1'
    H = {'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}

    def api(path, body=None, raw=False):
        return _req(api_base + path, json.dumps(body).encode() if body is not None else None,
                    H, raw=raw)

    def wait(jid):
        for _ in range(180):
            d = api(f'/jobs/{jid}')
            if d.get('job_state') in ('stopped', 'failed', 'cancelled'):
                return d
            time.sleep(10)
        raise SystemExit('Descript 任务超时')

    sz = os.path.getsize(src)
    imp = api('/jobs/import/project_media', {
        'project_name': os.environ.get('TITLE', 'clip-factory faithful transcript'),
        'add_media': {'m': {'content_type': 'video/mp4', 'file_size': sz}}})
    u = imp['upload_urls']['m']
    u = u.get('upload_url') if isinstance(u, dict) else u
    urllib.request.urlopen(urllib.request.Request(
        u, data=open(src, 'rb').read(), method='PUT',
        headers={'Content-Type': 'application/octet-stream'}), timeout=1800)
    wait(imp['job_id'])
    pid = imp['project_id']
    ag = api('/jobs/agent', {'project_id': pid, 'model': 'auto', 'prompt':
             'Add the imported media to the main composition timeline and transcribe the speech '
             'verbatim. Change nothing else.'})
    wait(ag['job_id'])
    comp = api(f'/projects/{pid}')['compositions'][-1]['id']
    srt = api('/export/transcript', {'project_id': pid, 'composition_id': comp, 'format': 'srt'},
              raw=True).decode()

    words = []
    cue_a = cue_b = 0.0

    def t2s(t):
        h, m, rest = t.split(':')
        s, ms = rest.split(',')
        return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000

    for line in srt.split('\n'):
        m = re.match(r'(\d\d:\d\d:\d\d,\d+) --> (\d\d:\d\d:\d\d,\d+)', line)
        if m:
            cue_a, cue_b = t2s(m.group(1)), t2s(m.group(2))
            continue
        if not line.strip() or line.strip().isdigit():
            continue
        toks = line.replace('Speaker:', ' ').split()
        if not toks:
            continue
        # 句级 cue：按 token 数把时间均摊，只用于定位，不可当切点真相源
        step = (cue_b - cue_a) / len(toks)
        for i, tk in enumerate(toks):
            words.append(dict(w=tk, start=round(cue_a + i * step, 3),
                              end=round(cue_a + (i + 1) * step, 3),
                              filler=bool(FILLER.match(tk.strip())),
                              approx_timing=True))
    return dict(vendor='descript', project_id=pid, words=words, silences=[])


def main():
    src = os.environ['SRC']
    vendor = os.environ.get('VENDOR', 'opus')
    out = os.environ.get('OUT', 'faithful.json')
    res = {'opus': opus, 'descript': descript}[vendor](src)
    dur = float(subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                                '-of', 'csv=p=0', src], capture_output=True, text=True).stdout or 0)
    res.update(source=os.path.basename(src), duration=round(dur, 2),
               fillers=[w for w in res['words'] if w['filler']])
    json.dump(res, open(out, 'w'), ensure_ascii=False, indent=1)
    print(f"{vendor}: {len(res['words'])} 词 | 口头禅 {len(res['fillers'])} 个 "
          f"| 静音标记 {len(res['silences'])} | → {out}")
    for w in res['fillers'][:20]:
        print(f"   {w['start']:7.2f}s  {w['w']}")


if __name__ == '__main__':
    main()
