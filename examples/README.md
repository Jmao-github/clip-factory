# Input files you write by hand

Two files live in `$WORKDIR` and are authored by you (or by an agent following `SKILL.md`). Everything else in the working directory is generated.

## `spec.json` — which segments become which clip

A list of clips. Each clip is cut from 2–5 **segments** ("观点段"), which are non-contiguous ranges of the source. Segment boundaries are where the shot resets and where the label card changes, so split on ideas, not on convenient silences.

| Field | Level | Required | Meaning |
|---|---|---|---|
| `slug` | clip | yes | Output name. `{slug}.cand.mp4` is the candidate; `promote.py` renames it to `{slug}.mp4`. |
| `speaker` | clip | no | Recorded in the decision table; attribution is inferred from content, not voiceprint. |
| `title` / `why_shareable` | clip | no | Your reasoning, carried into the decision table. Write it — the gate that asks "why this segment" is a human one. |
| `layout_force` | clip | no | `screen` or `camera`. Overrides layout detection, which a dark window behind the speaker can fool. |
| `tempo` | clip | no | 1.0–1.15. Speeds up speech without changing pitch; subtitles and labels scale with it. |
| `pip` | clip/seg | no | `false` removes the speaker picture-in-picture — use it when the source already has a floating self-view, so the same face never appears twice. |
| `a` / `b` | seg | yes | Source in/out in seconds. Snapped outward to word boundaries, then refined against the waveform. |
| `title` / `why` | seg | yes | Same as above: this is what the decision table is made of. |
| `label` | seg | no | Short English label card, top-left, shown for this segment. |
| `motion` | seg | no | `in` (slow push, default), `out` (pull back), `hold` (static). |
| `screen_rect` / `pip_rect` | seg | no | `[x, y, w, h]` override for sources whose layout drifts mid-talk. |

Practical notes, all of them learned the hard way:

- **Don't open a clip on a connective.** "But…", "So…", "And…" as the first word reads as though something was cut off — because it was.
- **Don't open on a very short function word.** Whisper will happily tag a 0.04s "I"; the acoustic start model then lands inside it and the finished clip begins on the next word. Gate 11 catches it, but it is cheaper not to do it.
- **Need more length? Add a segment, don't extend backwards into half a sentence.** Borrowing the tail of the previous thought is how clips end up incoherent.
- **Skip regions dense with fillers and self-corrections.** Whisper's word timestamps drift up to ~0.8s there, and every splice becomes a coin flip.
- **Target 45–58s.** Below 45 it feels like a fragment; above 58 the drop-off is steep.

## `glossary.json` — proper nouns, per session

`{"misheard form": "correct form"}`, applied to **subtitles only**. Build it in stage 0, before transcription, from the event page and the speaker's intro; top it up right after the transcript exists. Brand and product names are the single most common visible defect in auto-captioned clips, and they are entirely preventable.

See `glossary.example.json` for the two gotchas: decimal tokens are split by the transcriber, and a mapping whose key is also an ordinary English word will corrupt legitimate uses of that word.
