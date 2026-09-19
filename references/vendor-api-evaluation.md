# Descript API vs OpusClip API — a hands-on evaluation

Every endpoint of both APIs, called for real against the same 47-second finished clip, on 2026-09-18.
Nothing here is from a marketing page. Where a number appears, it was measured; where a control was
run, the control is reported alongside — including the one that reversed the conclusion.

> **中文速读**
> 1. Descript 的 Studio Sound 确实有效（降噪 6.2 dB），但**光是在 Descript 走一趟**就让信噪比掉 19.4 dB，净亏。没做反向对照的话，这个结论会完全搞反。
> 2. OpusClip 的 `GET /api/transcripts` 是本次最大发现：**词级时间戳 + 如实写出口头禅 + 静音标记 + 品牌名更准**，正好补上 whisper 的最大盲区。
> 3. whisper 对 uh/um 是**半聋**的：同一段音频，默认设置听出 0 个，加一句「逐字」提示词听出 4 个，两家商用 API 都听出 ~10 个。靠 whisper 删口头禅，等于只删它肯写下来的那部分。

---

## Why this was run

This pipeline deletes filler words by looking them up in a word-level transcript. A reviewer kept
reporting audible `uh` in finished clips across four rounds of fixes. Each round we fixed a *splice*
problem — reverb tails at the cut points — and each round the complaint came back.

The evaluation was originally scoped as "is Descript's Studio Sound worth adding as an audio node."
It ended up finding the actual cause of the complaint, which was not a splice problem at all.

## The finding that mattered

**The transcriber is half-deaf to filler words, and the pipeline can only delete what the
transcriber writes down.**

Same 48 seconds of audio, three transcribers:

| Transcriber | `uh` / `um` found |
|---|---|
| whisper-large-v3-turbo, default settings (what the pipeline used) | **0** |
| whisper-large-v3-turbo, with a one-line verbatim `initial_prompt` | **4** |
| Descript | **10** |
| OpusClip | **6** (on a different clip; matched Descript exactly on that one) |

The blindness is not uniform — it varies by region of the source, which is why it went unnoticed.
Across five delivered clips, the correlation with the pipeline's own filler-deletion counter is exact:

| Clip | fillers the pipeline deleted | fillers actually remaining |
|---|---|---|
| 1 | 8 | 0 |
| 2 | 11 | 0 |
| 3 | **0** | **10** |
| 4 | **0** | **6** |
| 5 | 11 | 0 |

`deleted = 0` never meant "this passage was clean". It meant "the transcriber wrote nothing down".

**None of the twelve verification gates could catch this**, and one of them is structurally incapable
of ever catching it: the re-transcription gate compares a whisper transcript against a whisper
re-transcription. Both sides share the same blindness, so it passes by construction. A gate that
compares a tool against itself does not verify the tool.

## The control that reversed a conclusion

First measurement of Studio Sound, against our own master:

| | noise floor | voice | SNR |
|---|---|---|---|
| our master | −79.6 dBFS | −20.3 dBFS | 59.3 dB |
| Descript + Studio Sound | −69.0 dBFS | −22.6 dBFS | 46.5 dB |

Read alone, that says Studio Sound made a clean recording 12.8 dB worse — a surprising result, and a
tempting one to publish. So the same composition was published a second time with Studio Sound
switched off, as a negative control:

| | noise floor | voice | SNR |
|---|---|---|---|
| our master | −79.6 dBFS | −20.3 dBFS | 59.3 dB |
| **Descript round-trip, no processing** | **−62.8 dBFS** | −23.0 dBFS | **39.9 dB** |
| Descript + Studio Sound | −69.0 dBFS | −22.6 dBFS | 46.5 dB |

The round-trip alone costs 19.4 dB of SNR. **Studio Sound is genuinely good — it recovers 6.2 dB of
that — it simply cannot pay back the cost of the trip.** The honest conclusion is narrow: Studio
Sound is for material that is already noisy and already inside Descript. For an already-clean master,
any round-trip is a net loss regardless of what you do while you are in there.

Video, same round-trip, measured on matched crop regions (the returned file is letterboxed, and
measuring the whole frame including the black bars produced a misleading 0.86× before the crop was
matched):

- 1280×650 in → 1280×720 out, letterboxed
- bitrate 5.16 Mbps → 2.37 Mbps
- Laplacian variance 0.95–0.97× at five sample points
- audio resampled 48 kHz → 44.1 kHz, AAC ~160 kbps both sides

## Descript — all 13 endpoints

Base: `https://descriptapi.com/v1`, bearer token.

| Endpoint | What it is for | Result |
|---|---|---|
| `GET /status` | Validate token, identify the connected drive | ✅ |
| `GET /projects` | List projects, with name/folder/date filters | ✅ |
| `GET /projects/{id}` | Media, durations, composition list | ✅ |
| `POST /jobs/import/project_media` | Create a project and upload media via a presigned PUT | ✅ ~40 s for 8 MB |
| `POST /jobs/agent` | **The core of the API.** Natural-language editing instructions | ✅ see below |
| `GET /agent/models` | Model catalogue with cost tiers | ✅ `auto`/haiku = low-mid, opus / gpt-5.5 / gemini-pro = high |
| `GET /jobs` | Recent jobs, 7-day default lookback, 30-day max | ✅ |
| `GET /jobs/{id}` | Status, progress label, result, **credits consumed** | ✅ |
| `DELETE /jobs/{id}` | Cancel a job | ⚠️ `409 Job is not running` on a finished job — running jobs only |
| `POST /export/transcript` | txt, markdown, html, rtf, docx, srt | ✅ all six; **sentence-level cues, no word timestamps** |
| `POST /jobs/publish` | Render + share link, 480p–4K, video or audio-only | ✅ see below |
| `GET /published_projects/{slug}` | Public metadata + signed download URL | ✅ rate limited 1000/h |
| `POST /edit_in_descript/schema` | One-time import link for a partner "Edit in Descript" button | ❌ requires `partner_drive_id` — **approved partners only** |

### The agent endpoint

Five instructions, each a separate job. Instruction-following was good: every constraint in the
prompt was respected, including the negative ones.

| Instruction | Credits | Outcome |
|---|---|---|
| Place media on timeline, transcribe | 11.6 | ✅ |
| Apply Studio Sound, change nothing else | 5.8 | ✅ measurably applied |
| Remove Studio Sound, restore original | 5.8 | ✅ made the negative control possible |
| Remove filler words, keep every real word | 15.5 | ✅ removed 9 `uh` + `you know` + a `like, uh, like` stutter, **touched no real word** |
| Transcribe a finished clip verbatim | 9.7–11.6 | ✅ |

The filler-removal job is worth singling out: a transcript diff before and after showed 14 tokens
removed, all of them fillers, with zero real-word deletions. This is the one place a vendor clearly
beats the local pipeline, and it beats it because its transcript is faithful, not because its editing
is smarter.

### Publish access levels

`private`, `unlisted` and `public` all succeeded; `drive` returned `403` naming the drive's allowed
levels. `unlisted` is link-only, which is the "anyone with the link, not discoverable" behaviour
people usually want.

**One sharp edge:** a composition has exactly **one** publish record. Publishing again with a
different access level *overwrites* the level on the existing link rather than creating a second one.
A test that walks through the levels therefore leaves the asset at whichever level ran last — check
and reset it afterwards.

## OpusClip — all 22 operations

Base: `https://api.opus.pro/api`, bearer token. Two practical notes before the table:

- The API sits behind Cloudflare, which rejects a default Python `urllib` user-agent with
  `403 error code: 1010`. Send a browser-like `User-Agent`.
- `POST /upload-links` (three-step resumable local upload) **is not in the published OpenAPI spec**
  but is required for local files. The spec's `videoUrl` field takes the resulting upload id.

| Endpoint | What it is for | Result |
|---|---|---|
| `POST /upload-links` | Local file upload (undocumented in the spec) | ✅ |
| `POST /clip-projects` | Create project, start clipping | ✅ 1 credit/minute, **10 credit minimum** |
| `GET /clip-projects/{id}` | Project state | ✅ field is `stage`, not `status`; also returns an auto-detected genre, delivery style and words-per-minute |
| `POST /clip-projects/{id}/update-visibility` | `DEFAULT` ↔ `PUBLIC` share link | ✅ both directions |
| `GET /exportable-clips` | The generated clips | ✅ produced 1 clip from a 47 s input, with a virality score and an auto-written headline |
| **`GET /transcripts`** | **Source transcript** | ✅ **the standout — see below** |
| `GET /brand-templates` | Layout, caption style, aspect ratio presets | ✅ |
| `POST /collections` | Create a collection | ✅ id field is `collectionId` |
| `GET /collections?q=mine` | List collections | ✅ `q` is an enum, not a page object |
| `POST /collection-contents` | Add a clip to a collection | ✅ |
| `POST /collection-contents/delete-collection-contents` | Remove a clip | ✅ |
| `POST /collections/{id}/export` | Export a collection | ✅ returns signed direct mp4 URLs |
| `DELETE /collections/{id}` | Delete a collection | ✅ |
| `POST /censor-jobs` | Profanity censoring | ✅ returned `No censored words found` inline, no job created |
| `GET /censor-jobs/{id}` | Censor job status | — not reachable: no job id is issued when there is nothing to censor |
| `POST /generative-jobs` | AI thumbnail generation | ⚠️ job accepted, then `UnsupportedSourceError` — **platform sources only (YouTube/Vimeo), not local uploads** |
| `GET /generative-jobs/{id}` | Thumbnail job status | ✅ (surfaced the error above) |
| `GET /social-accounts?q=mine` | Connected social accounts | ✅ returned an empty array |
| `POST /social-copy-jobs` | Generate post copy | ❌ **HTTP 500** with no connected account |
| `GET /social-copy-jobs/{id}` | Copy job result | — not reachable, creation 500s |
| `POST /post-tasks` | Publish to a connected account | ❌ **HTTP 500** |
| `POST /publish-schedules` | Schedule a publish | ❌ **HTTP 500** |
| `DELETE /publish-schedules/{id}` | Cancel a schedule | ✅ clean `400 Schedule task not found` |

**API quality, observed:** parameter errors are excellent — a bad `q` value replies with the exact
list of legal enum values. Unmet *business* preconditions are poor — all three social endpoints
return a bare `500` when no account is connected, where a `400` naming the missing precondition
would cost nothing.

### The transcript endpoint

Returned for a 47-second clip: 11 sentences, 143 real word tokens, 8 explicit `__silence` markers,
per-word `start`/`end` timestamps, all 6 filler words, speaker stutters preserved
(`I, I` / `the, the, the, the` / `s- go find`), and a product name transcribed correctly that the
local model consistently mangles.

For a pipeline that cuts on word boundaries and deletes fillers, this is a better input than either
the local model's output *or* Descript's export — the local model has the timestamps but not the
fillers, Descript has the fillers but not the timestamps, and this has both.

It also settled a caption error: two of the three transcribers agreed on a word the pipeline had
shipped incorrectly, against one vote for the shipped version.

## Where each tool actually belongs

| Pipeline node | Verdict |
|---|---|
| Word-level transcript with faithful fillers | **OpusClip `GET /transcripts`** |
| Formatted prose transcript (markdown / docx) | Descript `POST /export/transcript` |
| Natural-language editing on an existing project | Descript `POST /jobs/agent` |
| Translation / dubbing | Descript |
| Audio restoration | Neither, for already-clean masters — the round-trip costs more than the repair returns |
| Rendering | Neither — both re-encode below our bitrate and one letterboxes |
| Highlight selection | Neither — cross-model scoring already converges without a third opinion |
| Publishing to social | OpusClip has it; irrelevant if a human approves every post anyway |

## Method notes worth keeping

1. **Run the negative control before believing a measurement.** The Studio Sound result inverted once
   the round-trip cost was isolated. The first number was real and the first conclusion was wrong.
2. **Check that the measurement region matches.** A letterboxed return file made sharpness look 0.86×
   until the black bars were cropped out; the true figure was 0.96×.
3. **A tool cannot verify itself.** A gate comparing transcript A to transcript B from the same model
   proves only that the model is self-consistent.
4. **Stale intermediate files will silently redirect an experiment.** The first upload here was an
   older build artifact with the same name as the current one but different cut points. Check
   modification times against the manifest before uploading anything for comparison.
5. **Record what a write-endpoint left behind.** Walking through publish access levels left an asset
   at the last level tested, because the levels share one record.

---

## What this evaluation shipped

The finding was worth exactly one dependency swap and one new gate — not a rewrite. The pipeline's
own renderer, cutter, loudness stage, caption layer and selection remain unchanged, because on those
nodes it measured better than both vendors.

**`scripts/faithful_transcript.py`** — pulls a filler-faithful transcript from either vendor and
normalises it. The OpusClip backend returns word-level timestamps, explicit `__silence` markers and
the fillers, so it can serve as both the filler source and a cutting-grade word table. The Descript
backend returns sentence-level cues with approximated per-word timing — good enough to gate on, not
good enough to cut on, and it says so in the output.

**`scripts/filler_gate.py` (gate 13)** — re-hears every finished clip with a transcriber from a
different vendor before release. Wired into the executor and into the promote gate, with the same
evidence-freshness rule as every other gate.

**A free partial fix** — the existing boundary gate's full-clip filler scan now passes a verbatim
`initial_prompt` to the local model. It recovers roughly 40% of what it used to miss. It is a
mitigation, not the fix; the gate is the fix.

### Both controls, run before shipping

A gate that has only ever been seen passing is not a gate. Gate 13 was run in both directions first:

| Control | Clip | Expected | Result |
|---|---|---|---|
| Negative | one known to carry fillers | must go red | `FILLER-FAIL`, 10 fillers, timestamps at 3.7s / 5.9s / 14.7s / 16.9s / 20.0s / 27.6s / 37.9s / 38.5s / 45.2s / 47.6s |
| Positive | one known to be clean | must go green | `FILLER-CLEAN`, 0 fillers, 161 word tokens |

Cost: about 10 credits per clip, per run.

### What it costs to keep

One vendor subscription that would otherwise have been cancelled. The evaluation began as a case for
dropping OpusClip — it had lost three straight comparisons on rendering, selection and prompt
adherence, and the remaining approved use had never once been exercised. The endpoint that justifies
keeping it is one nobody had called.
