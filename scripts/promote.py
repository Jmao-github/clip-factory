#!/usr/bin/env python3
"""发布门卫：逐条核对全部 gate 证据，全绿才把 {slug}.cand.mp4 替换成正式片 {slug}.mp4。
旧有效成片在此之前绝不被触碰；任何缺证/失败/过期都指名 clip+gate（最窄重跑定位）。
证据文件：built.json(词完整性) / retranscribe.json / avcheck_out.json / greenbox_result.txt / loudness.json(响度)
/ final_vision_review.json(需 clips_pass 列表 = Gemini 意见 + 本人逐格人眼终裁)。
新鲜度：所有证据 mtime 必须 ≥ cand 文件 mtime（防拿旧检查放行新片）。"""
import json, os, sys
os.chdir(os.environ.get('WORKDIR','.'))
ONLY = os.environ.get('ONLY')

def load(p):
    return json.load(open(p)) if os.path.exists(p) else None

rt = {r['slug']: r for r in load('retranscribe.json') or []}
av = load('avcheck_out.json') or []
fv = (load('final_vision_review.json') or {}).get('clips_pass')
ld = {r['slug']: r for r in load('loudness.json') or []}
sa = {r['slug']: r for r in load('splice_audit.json') or []}
bc = {r['slug']: r for r in load('boundary_check.json') or []}
gb = open('greenbox_result.txt').read().strip().splitlines()[-1] if os.path.exists('greenbox_result.txt') else ''

blocked = []
for c in json.load(open('built.json')):
    slug = c['slug']
    if ONLY and slug != ONLY: continue
    cand = f'{slug}.cand.mp4'
    bad = []
    if not os.path.exists(cand):
        if os.path.exists(f'{slug}.mp4'):
            print(f'{slug}: 已是正式片（无候选待转正），跳过'); continue
        blocked.append((slug, ['无候选片也无正式片 ' + cand])); continue
    ct = os.path.getmtime(cand)
    if c.get('integrity') != 'PASS': bad.append(f"词完整性: {c.get('integrity')}")
    r = rt.get(slug)
    if not r: bad.append('缺 retranscribe 结果 → 跑 ONLY=%s rt2.py' % slug)
    elif not (r['ratio'] >= 0.85 and r['head_ok'] and r['tail_ok']):
        bad.append(f"重转写: ratio={r['ratio']} head={r['head_ok']} tail={r['tail_ok']}")
    segs = [x for x in av if x.get('clip') == slug]
    if not segs: bad.append('缺 avcheck 结果 → 跑 av_multi.py')
    else:
        mm = [x for x in segs if x.get('verdict') != 'MATCH']
        if mm: bad.append(f"图文一致性: {len(mm)} 段非 MATCH (seg {[x['seg'] for x in mm]})")
    if gb != 'GREENBOX-CLEAN': bad.append(f'绿框扫描: {gb or "缺 greenbox_result.txt"}')
    if fv is None: bad.append('缺 final_vision_review.json 的 clips_pass（Gemini+人眼终裁后写入）')
    elif slug not in fv: bad.append('视觉终审未过（不在 clips_pass）')
    l = ld.get(slug)
    if not l: bad.append('缺 loudness.json → 跑 loudness_check.py')
    elif not l['ok']: bad.append(f"响度不达标 {l['lufs']} LUFS / TP {l['tp']}")
    for nm, tbl, hint in (('splice_audit.json', sa, 'G12 残响'), ('boundary_check.json', bc, 'G11 边界词')):
        e = tbl.get(slug)
        if not e: bad.append(f'缺 {nm} → 跑对应机检')
        elif not e.get('ok'): bad.append(f'{hint} FAIL')
    for p in ('retranscribe.json','avcheck_out.json','greenbox_result.txt','final_vision_review.json','loudness.json','boundary_check.json'):
        if os.path.exists(p) and os.path.getmtime(p) < ct:
            bad.append(f'STALE: {p} 早于候选片，检查须在重建后重跑')
    # splice 审计的是 build 产物(base 的剪口)，在 overlay 前跑——新鲜度对 base 比(codex 原规则,0915实证不可省)
    if os.path.exists('splice_audit.json') and c.get('base') and os.path.exists(c['base']) \
            and os.path.getmtime('splice_audit.json') < os.path.getmtime(c['base']):
        bad.append('STALE: splice_audit.json 早于本次剪辑(base)，须重跑')
    if bad:
        blocked.append((slug, bad))
    else:
        os.replace(cand, f'{slug}.mp4')
        print(f'{slug}: 全 gate 绿 → 已替换正式片 {slug}.mp4')

if blocked:
    for slug, bad in blocked:
        for b in bad: print(f'{slug}: ✗ {b}')
    print('PROMOTE-BLOCKED'); sys.exit(1)
print('PROMOTE-OK')
