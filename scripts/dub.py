#!/usr/bin/env python3
"""多语言版链条（0915 实测跑通后固化）：
{slug}_base.mp4（无字幕干净版）→ Descript API 翻译+配音 → 取回
→ whisper 按目标语转写配音音频 → 我们自己烧目标语字幕（+可选段标签翻译）
→ loudnorm → {slug}_{lang}.mp4 + 机检报告。
用法：SLUG=01-html-not-timeline LANG=zh LANG_NAME="Simplified Chinese" python3 dub.py
credits：一条 50s 片 ≈25 AI credits（Creator 800/月）。
⚠️ 永远用 _base.mp4（烧过字幕的成片会双层字幕穿帮，0915 实翻）。"""
import json, os, re, subprocess, sys, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from envkey import get_key

SLUG = os.environ['SLUG']; LANG = os.environ.get('LANG_CODE', 'zh')
LANG_NAME = os.environ.get('LANG_NAME', 'Simplified Chinese')
BASE = f'{SLUG}_base.mp4'
K = get_key('DESCRIPT_API_KEY')
H = {'Authorization': 'Bearer ' + K, 'Content-Type': 'application/json'}
API = 'https://descriptapi.com/v1'

def req(path, body=None, method=None):
    r = urllib.request.Request(API+path, data=json.dumps(body).encode() if body else None,
                               headers=H, method=method)
    return json.load(urllib.request.urlopen(r, timeout=120))

def wait(job_id, tag):
    for i in range(90):
        d = req(f'/jobs/{job_id}')
        st = d.get('job_state')
        print(f'  {tag} {i}: {st} {(d.get("progress") or {}).get("label","")[:60]}', flush=True)
        if st in ('stopped', 'failed'): return d
        time.sleep(10)
    raise SystemExit(f'{tag} 超时')

# 1. 上传 base
sz = os.path.getsize(BASE)
imp = req('/jobs/import/project_media', {'project_name': f'clip-factory {SLUG} dub {LANG}',
        'add_media': {'m': {'content_type': 'video/mp4', 'file_size': sz}}})
u = imp['upload_urls']['m']; u = u.get('upload_url') if isinstance(u, dict) else u
urllib.request.urlopen(urllib.request.Request(u, data=open(BASE,'rb').read(), method='PUT',
    headers={'Content-Type': 'application/octet-stream'}), timeout=600)
wait(imp['job_id'], 'import')
P = imp['project_id']; print('project:', P)

# 2. Underlord 翻译+配音（不动画面）
ag = req('/jobs/agent', {'project_id': P, 'model': 'auto', 'prompt':
    f'Add the media to the main composition timeline, then translate the speech into {LANG_NAME} '
    f'and dub the entire video in {LANG_NAME} with an AI voice, keeping timing aligned to the original. '
    f'Do not add captions. Do not change any visuals.'})
r = wait(ag['job_id'], 'dub')
print('credits:', (r.get('result') or {}).get('ai_credits_used'))

# 3. 找译制 composition（新增的那条）并 publish 下载
proj = req(f'/projects/{P}')
comps = proj['compositions']
target = comps[-1]['id'] if len(comps) > 1 else comps[0]['id']
pub = req('/jobs/publish', {'project_id': P, 'composition_id': target,
                            'media_type': 'Video', 'resolution': '720p', 'access_level': 'private'})
r = wait(pub['job_id'], 'publish')
dl = (r.get('result') or {}).get('download_url')
raw = f'{SLUG}_{LANG}_raw.mp4'
urllib.request.urlretrieve(dl, raw); print('downloaded', os.path.getsize(raw))

# 4. whisper 目标语转写配音音频（词级）→ 烧目标语字幕
import mlx_whisper
subprocess.run(['ffmpeg','-v','error','-i',raw,'-vn','-ac','1','-ar','16000','_dub.wav','-y'], check=True)
w = mlx_whisper.transcribe('_dub.wav', path_or_hf_repo='mlx-community/whisper-large-v3-turbo',
                           word_timestamps=True, language=LANG, condition_on_previous_text=False)
words = [x for s in w['segments'] for x in s.get('words', [])]
print('dub words:', len(words))

from PIL import Image, ImageDraw, ImageFont
CJK = LANG in ('zh', 'ja', 'ko')
FB = '/System/Library/Fonts/Hiragino Sans GB.ttc' if CJK else '/System/Library/Fonts/Supplemental/Arial Bold.ttf'
fcap = ImageFont.truetype(FB, 42)
W2, H2 = 1280, 720   # Descript 输出 720p 画布（base 650 居中带边）
cues = []; cur = []; cs = None; oe = 0
for x in words:
    if cs is None: cs = x['start']
    cur.append(x['word'].strip()); oe = x['end']
    joined = ('' if CJK else ' ').join(cur)
    if (CJK and len(joined) >= 14) or (not CJK and len(cur) >= 6 and oe-cs >= 1.1) or oe-cs >= 2.6:
        cues.append([cs, oe, joined]); cur = []; cs = None
if cur: cues.append([cs, oe, ('' if CJK else ' ').join(cur)])
os.makedirs(f'caps/{SLUG}_{LANG}', exist_ok=True)
inputs = ['-i', raw]; ov = []; n = 1
for i, (a, b, txt) in enumerate(cues):
    img = Image.new('RGBA', (W2, H2), (0,0,0,0)); dr = ImageDraw.Draw(img)
    tw = dr.textlength(txt, font=fcap); x0 = (W2-tw)/2; y0 = H2-120
    for dx in range(-3,4):
        for dy in range(-3,4):
            if dx*dx+dy*dy <= 9: dr.text((x0+dx,y0+dy), txt, font=fcap, fill=(0,0,0,240))
    dr.text((x0,y0), txt, font=fcap, fill=(255,255,255,255))
    p = f'caps/{SLUG}_{LANG}/c{i:03d}.png'; img.save(p)
    inputs += ['-i', p]; ov.append((n, a, b)); n += 1
chain = []; prev = '[0:v]'
for k, (idx, a, b) in enumerate(ov):
    lbl = f'[v{k}]'; chain.append(f"{prev}[{idx}:v]overlay=0:0:enable='between(t,{a:.3f},{b:.3f})'{lbl}"); prev = lbl
open(f'fc_{SLUG}_{LANG}.txt','w').write(';'.join(chain))
outf = f'{SLUG}_{LANG}.mp4'
# 5. 烧字幕 + loudnorm（两遍式）
mj = subprocess.run(['ffmpeg','-i',raw,'-af','loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json','-f','null','-'],
                    capture_output=True, text=True).stderr
ln = json.loads(re.search(r'\{[^{}]*input_i[^{}]*\}', mj, re.S).group(0))
af = (f"loudnorm=I=-16:TP=-1.5:LRA=11:measured_I={ln['input_i']}:measured_TP={ln['input_tp']}"
      f":measured_LRA={ln['input_lra']}:measured_thresh={ln['input_thresh']}:offset={ln['target_offset']}:linear=true")
subprocess.run(['ffmpeg','-v','error']+inputs+['-filter_complex_script',f'fc_{SLUG}_{LANG}.txt','-map',prev,'-map','0:a',
    '-c:v','libx264','-preset','slow','-crf','16','-pix_fmt','yuv420p','-af',af,'-c:a','aac','-b:a','192k',
    '-movflags','+faststart',outf,'-y'], check=True)
d = float(subprocess.run(['ffprobe','-v','error','-show_entries','format=duration','-of','csv=p=0',outf],
                         capture_output=True, text=True).stdout)
print(f'DONE {outf} {d:.1f}s | 字幕{len(cues)}屏 | 交付前必过：人耳听译文 + 抽帧看字幕 + 决策表登记')
