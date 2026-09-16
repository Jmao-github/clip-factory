#!/usr/bin/env python3
"""faceMap（0915 负责人批准，预算 <$3/场）：Gemini 3.1-pro 整段看源视频，
出一张「时间段 → 布局 + 画面里每张人脸的位置」表 → facemap.json。
剪辑照表定 layout_force / pip 开关，不再靠临场撞见。用法：SRC=<视频> python3 facemap.py"""
import json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # 兄弟模块按引擎目录解析，不看 cwd
import gvid

PROMPT = """你在看一场 Google Meet 录制的 workshop（主讲人共享屏幕讲解）。从头到尾看完，输出一张 JSON 时间表，把全片切成若干连续区间，每个区间记录：

1. "start"/"end"：mm:ss
2. "layout"：
   - "screen_share"（画面主体是共享的屏幕内容）
   - "camera_only"（画面主体是摄像头人像，没有共享内容）
3. "faces"：这个区间画面上**每一张人脸**，逐个列出：
   - "pos"：位置（如 right-middle-tile / floating-in-share bottom-left / floating-in-share bottom-right / fullscreen）
   - "kind"："meet_tile"（Meet 布局右侧的摄像头小格）或 "floating_selfview"（悬浮在共享内容**里面**的自拍小窗，它是共享像素的一部分）或 "fullscreen_camera"
   - "who"：能认出是谁就写（同一个人用同一名字）
4. "second_person"：区间内若出现第二个人的脸（提问的社区成员等）标 true 并说明

⚠️ 特别注意悬浮自拍小窗：它常在共享内容的角落、会被拖动换位置。它的有无和位置变化必须单独成区间。
只输出 JSON 数组，不要其他文字。"""

src = os.environ.get('SRC', 'source.mp4')
out = gvid.ask(src, PROMPT, model='gemini-3.1-pro-preview')
open('facemap_raw.txt', 'w').write(out)
m = re.search(r'```json\s*(.*?)```', out, re.S) or re.search(r'(\[.*\])', out, re.S)
data = json.loads(m.group(1))
json.dump(data, open('facemap.json', 'w'), ensure_ascii=False, indent=1)
print(f'facemap.json: {len(data)} 个区间')
for iv in data:
    faces = '; '.join(f"{f.get('kind','?')}@{f.get('pos','?')}" for f in iv.get('faces', []))
    print(f"  {iv['start']}-{iv['end']} {iv['layout']:14} {faces}{'  +第二人' if iv.get('second_person') else ''}")
