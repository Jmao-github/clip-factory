<!-- 中文说明：README.zh.md -->

# clip-factory

Turn a 60-minute talk recording into a handful of 45–58 second clips that are actually publishable — and refuse to ship the ones that aren't.

This is not a "highlight finder". It is an opinionated editing pipeline with a **verification loop**: twelve machine checks plus a release gate stand between the renderer and the output folder. If a word got clipped in half, if a filler "uh" survived at a splice, if the loudness drifted, if a subtitle lost a word that is still in the audio — the pipeline says so, names the clip and the gate, and the clip does not get promoted.

Every rule in here was written after something went wrong on real footage. The `references/` docs record what broke and why the rule exists.

---

## What it does

```
source video + (optional) meeting notes
  │
  ├─ 1  three-way scan        word-level transcript (mlx-whisper) · silence map · scene cuts · layout detection
  │
  ├─ 2  content selection     full transcript scored by two independent model pools (Gemini + GPT),
  │                           five criteria, convergence = pick, disagreement = human call
  │
  ├─ 3  render                word-boundary cuts → smoothing layer (drop fillers, compress breaths)
  │                           → zero-upscale framing → lossless intermediates → subtitles → single crf16 pass
  │
  ├─ 4  verification          12 gates (see below). Any FAIL names the clip + gate; you fix the content
  │                           and re-run only that clip with ONLY=<slug>.
  │
  └─ 5  promote               evidence + freshness check → {slug}.cand.mp4 becomes {slug}.mp4
```

A ~60 minute source takes roughly 50 minutes of machine time for 3–5 clips. A human reviews two things: which segments to use, and how the finished clips feel.

## The rules that make the output different

- **Zero pixel upscaling.** A 720p screen-share region is 960×488 real pixels. Any output path magnifies at most **1.34×**. If the source doesn't have the pixels, the pipeline does not invent them.
- **Cuts land on word boundaries, never inside a word.** Eating more than 0.10s of a word is a hard failure, not a warning.
- **The smoothing layer is acoustic, not textual.** Whisper's timestamps drift 0.3–0.8s around fillers. Cutting by the word table alone leaves the tail of an "uh" ringing at every splice. Splice points are set from the actual waveform (RMS + zero-crossing rate).
- **One speaker on screen means one face on screen.** Screen-share layout is always *content + speaker PIP*; the pipeline never produces the same person twice.
- **Subtitles are held to the audio.** If a word is audible it appears in the caption; fillers never do; multi-word brand names are corrected on the word sequence so a line break can't defeat the glossary.
- **Nothing ships on a stale check.** The promote gate compares every evidence file's mtime against the candidate render.

## The twelve gates

| # | Gate | What it proves | Evidence |
|---|---|---|---|
| 1 | Word integrity | No half-cut words, no dropped words | `built.json` |
| 2 | Chunked re-transcription | The rendered file still says what it should (30s chunks; whole-file re-transcription hallucinates at the tail) | `retranscribe.json` |
| 3 | Frame/speech consistency | 3 frames per segment judged against the spoken line, majority vote | `avcheck_out.json` |
| 4 | Layout audit | Shot plan, no ping-ponging, caption durations | `layout_audit.json` |
| 5 | Content | Quotable claim present, no dangling opener, every segment has a stated reason | decision table |
| 6 | Sharpness regression | Laplacian variance at sample points must not drop below the previous render | `sharp.py` |
| 7 | Speaker attribution | Boundaries set by content evidence, not voiceprint | decision table |
| 8 | Green-box eradication | Full-length 2fps scan for a legacy highlight-box artifact; **zero frames scanned is a hard failure** | `greenbox_result.txt` |
| 9 | Visual review | Frames every ≤2.5s → grid → model reviewer + **human frame-by-frame ruling** | `vision_gemini.json` + `final_vision_review.json` |
| 10 | Loudness | −16 ±1 LUFS integrated, true peak ≤ −1.0 dBTP (EBU R128) | `loudness.json` |
| 11 | Boundary words | At every junction: last word of the previous segment present, first word of the next present, no orphan filler within ±0.45s | `boundary_check.json` |
| 12 | Splice reverb audit | Waveform check for filler tails and glued-on "uh" (transcription is deaf to this — it must be measured acoustically) | `splice_audit.json` |

Gate 9 is deliberately not fully automatic. The model reviewer over-reports; a person rules on each grid before anything is promoted.

## Requirements

- macOS or Linux, Python 3.10+
- `ffmpeg` / `ffprobe` on PATH
- `pip install -r requirements.txt` (`mlx-whisper` is Apple-Silicon only; on other hardware swap in `openai-whisper` or `faster-whisper` and keep `word_timestamps=True`)
- A Gemini API key for the content-scoring and visual-review steps (`GEMINI_API_KEY`)
- Optional: `OPENAI_API_KEY` for the second scoring pool, `OPUSCLIP_API_KEY` for third-opinion highlight finding, `DESCRIPT_API_KEY` for the dubbing chain

Keys are read from the process environment first, then from `$CLIP_FACTORY_ENV`, `./.env`, or `~/.clip-factory.env`. Copy `.env.example` to `.env` to get started. **`.env` is gitignored — never commit a key.**

## Quick start

```bash
git clone https://github.com/<you>/clip-factory.git
cd clip-factory && pip install -r requirements.txt
cp .env.example .env && $EDITOR .env          # add GEMINI_API_KEY

export WORKDIR=/path/to/this-session          # all artifacts land here
export SRC="$WORKDIR/source.mp4"

# 1. audio + word-level transcript
ffmpeg -i "$SRC" -vn -ac 1 -ar 16000 "$WORKDIR/audio.wav"
python3 -c "import mlx_whisper,json; json.dump(mlx_whisper.transcribe('$WORKDIR/audio.wav', \
  path_or_hf_repo='mlx-community/whisper-large-v3-turbo', word_timestamps=True, language='en'), \
  open('$WORKDIR/whisper.json','w'))"

# 2. pick segments → write spec.json   (see examples/spec.example.json,
#    and references/selection_prompt_template.txt for the scoring prompt)

# 3-4. build, caption, and run every gate in order
python3 scripts/run_pipeline.py

# 5. rule on the visual grids yourself, write the passing slugs into
#    final_vision_review.json, then:
python3 scripts/promote.py
```

Any gate failure names a clip and a gate. Fix the content, then re-run just that clip:

```bash
ONLY=02-my-clip python3 scripts/build.py     # build/overlay/rt2/boundary/av/vision all honour ONLY
```

## Using it as a Claude Code skill

`SKILL.md` is written for an agent. Drop the repo into your skills directory and the agent gets the whole pipeline, including the failure archive:

```bash
git clone https://github.com/<you>/clip-factory.git ~/.claude/skills/clip-factory
```

It works fine without an agent too — every script is a plain CLI.

## Layout

```
SKILL.md                              agent-facing operating instructions
references/WORKFLOW.md                the source of truth for every threshold and rule
references/Clip Selection Rubric.md   what makes a segment worth clipping
references/Pacing Baseline.md         measured pacing baselines, including two failed experiments
references/selection_prompt_template.txt
scripts/                              the pipeline (build, overlay, gates, promote)
examples/                             example spec.json and glossary.json
```

## Honest limitations

1. **The source resolution is the ceiling.** The pipeline's own losses are at zero; past that you need a better recording.
2. **Frame/speech consistency samples 3 frames per segment.** Gate 9 backstops it with a full sweep, but a suspicious segment deserves human eyes.
3. **The scoring criteria were written by one person.** Two independent model pools and a logged disagreement list are the mitigation, not a proof of neutrality.
4. **The smoothing layer is only validated on single-speaker English.** Multi-speaker crosstalk is excluded by a hard filter before it gets that far.
5. **The 45–58s window comes from ad-creative baselines**, not from this project's own published-performance data.
6. **Speaker attribution is inferred from content**, not from voiceprints.
7. **Reference docs are in Chinese.** `SKILL.md` and `references/` are the working notes as written; this README is the English entry point. Translation PRs welcome.

## Before you publish a clip

The last check is human and cannot be automated: look at the actual frames. If the speaker's file browser, chat window, or mailbox is visible, read what's in it. On one real session the closing shot exposed a third party's real name in a filename — the fix was to move the cut five seconds earlier, not to blur it.

## License

MIT — see [LICENSE](LICENSE).
