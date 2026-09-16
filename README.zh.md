# clip-factory（中文说明）

> English: [README.md](README.md)

把一场 60 分钟的分享录制，做成几条 45–58 秒、**可以直接发出去**的短片；做不合格的那几条，它会拦下来不让你发。

这不是一个"自动找高光"的工具。它是一条有主张的剪辑流水线，核心是**验证闭环**：渲染器和输出目录之间隔着 12 道机检 + 一道发布门。词被切了一半、剪口上残着一个 "uh"、响度飘了、字幕丢了一个音频里明明有的词——它会指名是哪条片的哪道 gate，然后这条片不予转正。

里面每一条规则，都是在真实素材上翻过车之后才写下来的。`references/` 里记着翻的是什么车、规则为什么长这样。

---

## 它做什么

```
源视频 +（可选）会议纪要
  │
  ├─ 1 三路扫描      词级转写(mlx-whisper) · 气口表 · 画面变化点 · 布局探测
  │
  ├─ 2 内容筛选      全文喂给两个互相独立的模型池（Gemini + GPT）打分，
  │                  五项判据；两榜收敛=定段，分歧=人来裁
  │
  ├─ 3 出片          词边界切点 → 顺滑层（删口头禅、压气口）→ 零推近机位
  │                  → 无损中间件 → 字幕 → 单代 crf16
  │
  ├─ 4 验证闭环      12 道 gate（见下）。任何 FAIL 都指名 clip + gate，
  │                  改完内容用 ONLY=<slug> 只重跑那一条，不推倒重来
  │
  └─ 5 promote       核证据 + 核新鲜度 → {slug}.cand.mp4 才变成 {slug}.mp4
```

一场 60 分钟的源片，出 3–5 条大约需要 50 分钟机器时间。人只需要看两件事：选哪些段，和成片好不好看。

## 让成片不一样的那几条规则

- **零像素推近。** 720p 的共享屏区域只有 960×488 个真实像素。任何输出路径最多放大 **1.34×**。源片没有的像素，管线不替它编。
- **切点永远落在词边界，绝不切进词里。** 吃掉一个词超过 0.10 秒就是硬失败，不是警告。
- **顺滑层按波形走，不按词表走。** whisper 给口头禅标的时间会漂 0.3–0.8 秒；只按词表切，每个剪口都会残着 "uh" 的尾巴。切点按真实波形（RMS + 过零率）定。
- **一个讲者，画面上就只准有一个头像。** 共享屏布局恒为"内容 + 讲者小窗"，同一个人绝不会在画面上出现两次。
- **字幕对齐音频。** 音频里听得见的词，字幕上就得有；口头禅一个都不上字幕；多词品牌名在词序列上替换，换行也打不断。
- **过期的检查一律不放行。** 发布门会拿每份证据文件的时间戳去比候选片的时间戳。

## 12 道 gate

| # | Gate | 它证明什么 | 证据 |
|---|---|---|---|
| 1 | 词完整性 | 没有半截词、没有丢词 | `built.json` |
| 2 | 分块重转写 | 成片里说的还是该说的（30 秒分块——整文件重转写会在尾部幻听） | `retranscribe.json` |
| 3 | 图文一致性 | 每段取 3 帧对口播内容判，多数决 | `avcheck_out.json` |
| 4 | layout | 机位、禁乒乓、字幕时长 | `layout_audit.json` |
| 5 | 内容 | 有可引用论断、开头不是悬空连接词、每段都写得出"为什么" | 决策表 |
| 6 | 锐度回归 | 重渲后抽样点的 Laplacian 方差不得低于上一版 | `sharp.py` |
| 7 | 说话人 | 按内容证据定边界，不靠声纹 | 决策表 |
| 8 | 绿框根除 | 全片 2fps 扫历史遗留的高亮框；**扫到 0 帧=硬失败** | `greenbox_result.txt` |
| 9 | 成片视觉审查 | ≤2.5 秒抽帧拼网格 → 模型毙稿官 + **本人逐格亲眼裁决** | `vision_gemini.json` + `final_vision_review.json` |
| 10 | 响度 | −16 ±1 LUFS，真峰值 ≤ −1.0 dBTP（EBU R128） | `loudness.json` |
| 11 | 边界词 | 每个接口：上段末词在、下段首词在、±0.45 秒内无孤立口头禅 | `boundary_check.json` |
| 12 | 拼接点残响 | 按波形查残响和粘连的 "uh"（转写对这个是聋的，必须测声学） | `splice_audit.json` |

第 9 道故意不做成全自动：模型毙稿官误报很多，人必须逐格裁完才准转正。

## 需要什么

- macOS 或 Linux，Python 3.10+
- PATH 上有 `ffmpeg` / `ffprobe`
- `pip install -r requirements.txt`（`mlx-whisper` 只支持 Apple Silicon；其他硬件换 `openai-whisper` 或 `faster-whisper`，保留 `word_timestamps=True` 即可）
- 一个 Gemini API key（内容打分 + 视觉审查）：`GEMINI_API_KEY`
- 可选：`OPENAI_API_KEY`（第二个打分池）、`OPUSCLIP_API_KEY`（第三方意见找高光）、`DESCRIPT_API_KEY`（多语言配音链）

key 先读进程环境变量，再依次找 `$CLIP_FACTORY_ENV`、`./.env`、`~/.clip-factory.env`。把 `.env.example` 复制成 `.env` 填进去即可。**`.env` 已在 .gitignore 里——永远不要把 key 提交上去。**

## 快速开始

```bash
git clone https://github.com/<你>/clip-factory.git
cd clip-factory && pip install -r requirements.txt
cp .env.example .env && $EDITOR .env          # 填 GEMINI_API_KEY

export WORKDIR=/path/to/this-session          # 所有产物落这
export SRC="$WORKDIR/source.mp4"

# 1. 抽音频 + 词级转写
ffmpeg -i "$SRC" -vn -ac 1 -ar 16000 "$WORKDIR/audio.wav"
python3 -c "import mlx_whisper,json; json.dump(mlx_whisper.transcribe('$WORKDIR/audio.wav', \
  path_or_hf_repo='mlx-community/whisper-large-v3-turbo', word_timestamps=True, language='en'), \
  open('$WORKDIR/whisper.json','w'))"

# 2. 选段 → 写 spec.json（示例见 examples/，打分 prompt 见 references/selection_prompt_template.txt）

# 3-4. 出片 + 按顺序跑完全部 gate
python3 scripts/run_pipeline.py

# 5. 自己逐格看 vrev/*_grid*.jpg，把通过的 slug 写进 final_vision_review.json，然后：
python3 scripts/promote.py
```

任何 gate 失败都会指名 clip 和 gate。改完内容只重跑那一条：

```bash
ONLY=02-my-clip python3 scripts/build.py     # build/overlay/rt2/boundary/av/vision 都支持 ONLY
```

## 当作 Claude Code skill 用

`SKILL.md` 是写给 agent 看的。把仓库放进 skills 目录，agent 就拿到了整条流水线，连翻过的车一起：

```bash
git clone https://github.com/<你>/clip-factory.git ~/.claude/skills/clip-factory
```

不用 agent 也完全能跑——每个脚本都是普通命令行工具。

## 不粉饰的已知弱点

1. **源片分辨率就是天花板。** 管线自身的损失已经清零，再往上只能提高录制质量。
2. **图文一致性每段只看 3 帧。** 第 9 道 gate 用全程抽帧兜底，但可疑段值得人再看一眼。
3. **打分判据是一个人写的。** 两个独立模型池 + 分歧留档是缓解手段，不等于中立。
4. **顺滑层只在英文单人讲解上验证过。** 多人抢话的素材在更早的硬门槛就被挡掉了。
5. **45–58 秒这个区间来自广告素材基线**，不是本项目自己的发布数据。
6. **说话人归属靠内容推断**，不是声纹。

## 发片之前，最后一眼

最后一道检查是人做的，自动化不了：把成片的关键帧真的看一遍。如果讲者的文件浏览器、聊天窗口、邮箱出现在画面里，把里面的字读清楚。有一次成片的收尾镜头里，文件名带出了第三方的真实姓名——正确的处理是把切点往前挪 5 秒，而不是打码。

## License

MIT，见 [LICENSE](LICENSE)。
