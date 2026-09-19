---
name: clip-factory
description: "Turn a long recording (workshop, podcast, conference talk) into 45-58s publish-ready clips: word-level transcription, dual-model segment scoring, filler-word removal with acoustic splice repair, zero-upscale rendering, burned-in captions, then thirteen machine gates plus a release gate that refuse to promote a clip that failed anything. Use when the user asks to cut clips / shorts / highlights from a recording, repurpose a talk into social video, or hands over a recording file or meeting-notes link and wants clips out. 把长视频（workshop/播客/分享录制）加工成 45-58 秒、可直接发布的精华短片——完整流水线：取素材→词级转写→双模型内容评分选段→顺滑剪辑（删口头禅/压气口）→零推近高品质渲染→十三道机检验证闭环。当用户说「把这场 workshop 剪成短片 / 出几条 clip / 剪精华 / 给这条录制出宣传片」，或甩来一个录制文件 + 会议纪要链接要出片时触发。也覆盖 OpusClip 辅助（第二意见找高光）。质量铁律=源片像素不够就不放大（≤1.34×），一切阈值以 references/WORKFLOW.md 为真相源。发布动作永远等人点头。"
license: MIT
compatibility: "Requires ffmpeg/ffprobe on PATH, Python 3.10+ with numpy and pillow, a word-level transcriber (mlx-whisper on Apple Silicon), and a Gemini API key for the scoring and visual-review gates."
metadata:
  version: "8.0"
  source: https://github.com/Jmao-github/clip-factory
---

# clip-factory

一场 55-75 分钟录制 → N 条 45-58s 成片。机器时间 ~50 分钟；负责人只 review 选段方向与成片观感。

## 快速开始

```bash
export WORKDIR=/path/to/your/clips/<本场目录>   # 工作目录（所有产物都落这）
export SRC="$WORKDIR/source.mp4"                # 源视频
export GEMINI_API_KEY=...                       # 或写进 .env（见 .env.example）
python3 <repo>/scripts/run_pipeline.py          # 一键执行器；单步用法见 WORKFLOW
```

## 五阶段（顺序执行，每步产物是下一步输入）

### 0. 取素材 + 专名表
- 云盘下载被拒时**按账号逐个试**（用有访问权的那个账号；Google Drive 的 `/u/N` 槽位映射会漂移，不可信）
- Granola note 只当**内容地图**（summary+讲者边界线索）。⚠️ 它的转写连品牌名都错（treg→track），**永不用于切点/字幕**
- `ffprobe` 核分辨率——720p 是常态，共享屏区域仅 960×488 像素，这决定后面所有画质规则
- **建本场专名表 `WORKDIR/glossary.json`**（`{"错听形":"正确形"}`）：从活动页/Granola/讲者自介收齐讲者名/产品名/术语，转写完成后立即扫全文补录——主动预防字幕错，不等终审抓（overlay.py 自动合并进 SUBFIX，场表覆盖默认表）

### 1. 三路扫描（并行 ~6min）
```bash
# 词级转写（切点与字幕唯一真相源）
python3 -c "import mlx_whisper,json; json.dump(mlx_whisper.transcribe('$SRC'.replace('.mp4','.wav') if False else 'audio.wav', path_or_hf_repo='mlx-community/whisper-large-v3-turbo', word_timestamps=True, language='en'), open('whisper.json','w'))"
# 先 ffmpeg -i $SRC -vn -ac 1 -ar 16000 audio.wav
ffmpeg -i audio.wav -af silencedetect=noise=-32dB:d=0.4 -f null - 2>&1 | grep -oE "silence_(start|end): [0-9.]+" > silence.txt
ffmpeg -i "$SRC" -vf "crop=960:488:0:132,fps=2,select='gt(scene,0.12)',showinfo" -an -f null - 2>&1 | grep -oE "pts_time:[0-9.]+" | sed 's/pts_time://' > scenes.txt
```
布局探测 `layoutdet.py`：右上角灰度均值 <20=共享屏 / ≥20=纯摄像头。**不探测会翻车**（讲者停共享后仍抠 PIP → 灰块盖脸，实翻过）。

### 2. 内容筛选 ★ 决定成败
把 whisper 整理成句子级带时间戳全文，**全文一次性**喂评分器（模板 `references/selection_prompt_template.txt`），不抽样：
- `gtext.py` 走 Gemini 池 + 同 prompt 走 **GPT-5.2** 独立池（`OPENAI_API_KEY`，独立性=换厂；判据 prompt 是 Claude 写的，不用 Claude 评）
- 五判据：lesson（可迁移>工具tip）/ useful / shareable / standalone / **not_promo**（自我推销降权；宣传片任务豁免）
- 硬门槛：自洽无外部指代 · 无悬空承诺 · 无粗口/demo翻车 · 非多人抢话 · 可裁 45-58s
- 两榜收敛=定段；分歧=列给负责人裁。说话人靠内容证据（自报名/自家产品）定边界，非声纹

### 3. 出片（`build.py` + `overlay.py`，spec.json 驱动）
spec 每段带 `a/b/title/why`；流程=词边界切点→smooth 顺滑层→机位→无损中间件→字幕。
**画质 v2 铁律**（负责人拍板"质量第一"）：
- **零像素推近**：放大 ≤1.34×（全景 1280/960 封顶）；**高亮绿框 2026-09-06 负责人拍板永久禁用，F 机位废除（F→W）**；共享屏布局恒为**内容+右下 PIP 人脸**（有 slide/内容时内容和人脸必须同在，纯人脸大画面仅限源本就纯摄像头或屏幕内容与口播无关）
- 全链 lanczos + unsharp 5:5:0.35；中间件 x264 **qp0 无损**；成片**单代 crf16/slow**
- 每机位 ≥6s、禁乒乓；屏幕内容与口播相关时**禁人像大画面**
- 顺滑层：句末气口 ≤0.55s / 逗号 0.32 / 词间 0.18；uh/um 整词删；只删整词与静音
- 字幕 ≤2.6s/屏；字幕专名修正 = 默认 SUBFIX + 本场 `glossary.json`，只改字幕不动音频（whisper 品牌名必错：treg/Ahrefs/Qwen3/Modal…）
- 标签卡文本走 spec.json 每条 `labels` 字段；成片先落 **`{slug}.cand.mp4` 候选片**，正式片只能由 promote 门替换

### 4. 验证闭环（任何 FAIL 修内容后 `ONLY=<slug>` 窄重跑该条，不放宽规则）
build/overlay/rt2/vision_review 均支持 `ONLY=<slug>`：只重建/重查单条，结果**合并写回**不覆盖他条——不再全量推倒 50 分钟。
| 检查 | 工具 |
|---|---|
| 词完整性（0 削半 0 丢词） | build.py 内建 |
| 分块重转写（30s 块防尾部幻觉）锚点+相似度≥0.85 | `rt2.py`（BUILT/RT env） |
| 图文一致性：每段 25/50/75% 三帧 Gemini 严判多数决 | `av_multi.py`（新场景先跑正负对照验判别力） |
| 锐度回归（重渲类改动 Laplacian 全点数≥旧版） | `sharp.py` |
| **绿框根除**：成片全程 2fps 扫绿框色签名 | `greenbox_scan.py`（新·0906） |
| **成片视觉审查**：≤2.5s 间隔全程抽帧 → Gemini 毙稿官逐格严判 + **本人逐格亲眼裁决**（发布前最后一关，Gemini 误报要人裁，真事故修完重跑） | `vision_review.py`（新·0906，负责人拍板必过） |
| layout/内容/说话人边界 | 见 WORKFLOW §4 |
| **口头禅终检 G13**：独立于 whisper 的转写器复听成片，uh/um 必须为 0（whisper 对 filler 半聋，G2 是它比它自己，结构上查不出来） | `filler_gate.py`（新·0918） |
| **promote 发布门**：核全部 gate 证据(含 G13)+新鲜度（证据 mtime ≥ 候选片），全绿才 `cand→{slug}.mp4`；缺证/失败/过期指名 clip+gate 退出非零。**旧有效成片在 promote 前绝不被触碰** | `promote.py`（新·0913） |

### 5. 交付
成片（Title Case 命名）+ 决策表（每段时间码/原话/为什么）+ 排期文案草稿。**发布永远等负责人点头**。

## OpusClip（Pro 已开，key=OPUSCLIP_API_KEY，API 月额 900 credits，1 credit=1 源分钟）
- **只用**：第二意见找高光（`opus_upload.mjs` 官方 4 步直传，绕 CLI 60s PUT bug；~55 credits/场）
- **不用（三连实测出局）**：①成片直出——品牌名错（Track/GroqBot）、画面不裁；②customPrompt 不遵从（叫它 skip 自我推销，#1/#2 仍是推销段）；③**混合渲染也不用**——2026-09-06 实测（项目 P30906194GqO，`opus_hybrid.mjs` range 渲染）：其"1080p"是未裁 720p 全帧强拉，Laplacian 锐度 416–522 vs 自有管线 1591–2046，**差 3–4 倍**，不过负责人的高清线。证据 `hybrid_sharpness.json`
- 提交前必须把平台的版权提示原文念给用户（上传他人素材前的确认环节，不可跳过）

## 坑档案（全部实翻过）
1. Granola 转写不可信（品牌名/人名错）→ 只当地图
2. 布局不探测 → 灰块盖脸
3. 像素推近 → 文字糊（负责人亲自抓的帧）→ 零推近+高亮框
4. 出点压词起点 → 整词被吃且 straddle 查不出 → DROPPED 检查
5. whisper 整文件重转写 → 尾部幻觉 → 30s 分块
6. 尾锚点纯序列比对 → 转写方差假阴性 → 内容词 75% 模糊命中
7. 字幕一屏含长静音 → 4.2s 超长屏 → 词间空隙>0.5s 强制断屏
8. vdl.py 全局 download-archive 去重 → 删了文件重下被静默跳过
9. 字幕词映射用严格包含 → 被帧对齐削掉几十毫秒的整词从字幕消失（音频里还在）；专名表在单屏文本上 re.sub → 品牌名跨屏就整条失效。两条都已改（WORKFLOW §3.5c）
10. 片头/段首挑 0.0x 秒的功能词或弱读 but/and/so → 声学起点落进词内，G11 必 FAIL；补时长加内容段，别往前借半句
11. 成片里露出讲者的 Finder/聊天窗 → 可能带第三方真人姓名，发布前必须逐帧看清（WORKFLOW 末节）
12. **删口头禅只能删转写器写下来的**：whisper 对 uh/um 半聋且不均匀（同段音频默认 0 / 逐字提示 4 / 商用转写器 10），`dropped=0` 不等于干净。真相源用 `faithful_transcript.py`，终检用 G13（WORKFLOW §4b）
13. **一个工具不能验证它自己**：G2 拿 whisper 比 whisper，对 whisper 的盲区永远绿。任何"自己比自己"的 gate 都要配一个换厂的独立检查

## 真相源
阈值/规则全文 = `references/WORKFLOW.md`（v3）；选段判据（留存法则/视觉节奏门槛/硬门槛）= `references/Clip Selection Rubric.md`；节奏实测基线 = `references/Pacing Baseline.md`；选段 prompt 模板 = `references/selection_prompt_template.txt`。
