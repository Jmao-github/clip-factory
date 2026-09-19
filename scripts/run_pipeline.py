#!/usr/bin/env python3
"""clip-factory 一键执行器（0915，负责人拍板"产出稳定是关键"后固化）。
前提：WORKDIR 里已有 source.mp4 / whisper.json / spec.json（选段已定）。
之后一条命令跑完：build → overlay → rt2(串行!) → greenbox → loudness → av → vision
→ 打印人裁清单 → （人签 clips_pass 后）promote。
纪律（全部实翻过才写进来的）：
- rt2 必须单独串行跑（与重负载并发会出 whisper 假 FAIL）
- 每步失败立即停并指名步骤，不带病往下走
- vision 之后必须人裁，本脚本到此为止，promote 由人签字后单独跑
用法：WORKDIR=<dir> SRC=<dir>/source.mp4 python3 run_pipeline.py
"""
import json, os, subprocess, sys

from pathlib import Path
ENGINE = Path(__file__).resolve().parent
WD = os.path.abspath(os.environ.get('WORKDIR', '.'))
os.chdir(WD)
ENV = dict(os.environ, WORKDIR=WD, SRC=os.environ.get('SRC', os.path.join(WD, 'source.mp4')), BUILT='built.json')

def step(name, cmd, expect=None):
    if cmd[0] == 'python3': cmd = [sys.executable, str(ENGINE / cmd[1]), *cmd[2:]]
    print(f'\n===== [{name}] =====', flush=True)
    r = subprocess.run(cmd, env=ENV, capture_output=True, text=True)
    out = (r.stdout or '') + (r.stderr or '')
    print(out[-1500:])
    if r.returncode != 0:
        sys.exit(f'✗ 步骤 [{name}] 退出码 {r.returncode}——修完后从这步重跑（窄重跑 ONLY=<slug>）')
    if expect and expect not in out:
        sys.exit(f'✗ 步骤 [{name}] 未见 "{expect}"——按输出指名的 clip+gate 修，不放宽规则')
    return out

step('build 出片', ['python3', 'build.py'], 'PASS')
step('splice 拼接点残响声学审计', ['python3', 'splice_audit.py'], 'SPLICE-PASS')
step('overlay 字幕/标签/响度', ['python3', 'overlay.py'])
step('rt2 重转写（串行）', ['python3', 'rt2.py'])
r = json.load(open('retranscribe.json'))
bad = [x['slug'] for x in r if x['ratio'] < 0.85 or not (x['head_ok'] and x['tail_ok'])]
if bad: sys.exit(f'✗ rt2 未达标: {bad}')
step('boundary 边界词完整（机器耳）', ['python3', 'boundary_check.py'], 'BOUNDARY-PASS')
gb = step('greenbox 绿框扫描', ['python3', 'greenbox_scan.py'], 'GREENBOX-CLEAN')
Path('greenbox_result.txt').write_text(gb)
step('loudness 响度', ['python3', 'loudness_check.py'], 'LOUDNESS-PASS')
step('av 图文一致', ['python3', 'av_multi.py', 'built.json', 'avcheck_out.json'], 'SEGMENTS-PASS')
if os.environ.get('FILLER_GATE', '1') != 'skip':
    # G13：独立于 whisper 的转写器复听成片。G2 是 whisper 比 whisper，对口头禅结构上查不出来。
    # 每条 ≈10 credits；确实不想花就显式 FILLER_GATE=skip，但那等于自愿放弃这道防线。
    step('filler 口头禅终检（独立转写器）', ['python3', 'filler_gate.py'], 'FILLER-CLEAN')
step('vision 成片视觉审查', ['python3', 'vision_review.py'])
print('''
===== 机检全绿。剩两步是人的活 =====
1. 人裁：逐格看 vrev/*_grid*.jpg（Gemini 报警按判据裁决，硬事故类不许放行）
   → 裁完把通过的 slug 写进 final_vision_review.json 的 clips_pass
2. promote：python3 promote.py   （证据全绿+新鲜才转正）''')
