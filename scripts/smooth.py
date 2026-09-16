#!/usr/bin/env python3
"""smooth — Descript 式顺滑层：删口头禅 + 压缩气口，输出 keep-span 列表。
输入：whisper.json（词级时间戳）+ EDL 段落；输出：每段的微片段保留表。
原则：只删「词」和「静音」，永不切进一个词内部。
"""
import json, re

FILLER = re.compile(r"^\s*(uh|um|erm|mm|hmm|mhm)[,.?!…\-]*\s*$", re.I)

# 0915晚·负责人抓「每删一个uh就留一个残响」：whisper 给 filler 标的时间不准，
# 删除后按 (word.start - cap) 保留的"气口"里常带着 uh 的真实发声。
# 声学精修：拼接点用真实波形找静音谷——起点掐掉谷前残响，终点顺着发声延到谷底(防切词尾)。
VOICE_TH = 0.012   # 16k mono float RMS 阈（本源实测：静音≤0.005，语音≥0.02）
CONS_HEAD = 'sfzcxhptkbdgjqvw'   # 以辅音字母开头的词：起声应是嘶音/爆破，不该是长元音

def _glue_skip(rms, zcr, t_on, wtext):
    """粘连 uh 判别（0915 晚，ZCR 实测 911.64 案）：删过 filler 且下一词以辅音开头，
    但接缝先出现 ≥0.10s 的低ZCR元音段 → 该元音=uh，切到辅音过渡点(高ZCR升起/RMS谷)。"""
    if rms is None or zcr is None or not wtext: return None
    if wtext.strip().strip('.,?!').lower()[:1] not in CONS_HEAD: return None
    head = 0.0; u = t_on
    while rms(u) >= VOICE_TH and zcr(u) < 0.25 and head < 0.45:
        u += 0.01; head += 0.01
    if head < 0.10: return None          # 起声不是长元音：就是词本体
    limit = t_on + head + 0.15
    while u < limit:                     # 找辅音过渡：ZCR 升起 或 RMS 谷
        if zcr(u) >= 0.30 or rms(u) < VOICE_TH: return u - 0.01
        u += 0.01
    return None

def _refine_start(rms, s, wstart, zcr=None, wtext='', filler_adjacent=False):
    """发声块模型：扫 [s, wstart+0.9] 全部发声块 → 词块=第一个延伸过 wstart+0.08 的块
    （残响块短、死在词标前；whisper 词头偏早/偏晚都被覆盖）→ 起点=词块前 ≤0.10s 呼吸、
    且不早于上一块结束(残响整段排除)；粘连 uh 再对词块头做 ZCR 判别。"""
    if rms is None: return s
    blobs = []; t = s; cur = None
    while t < wstart + 0.9:
        if rms(t) >= VOICE_TH:
            if cur is None: cur = t
        elif cur is not None:
            blobs.append((cur, t)); cur = None
        t += 0.01
    if cur is not None: blobs.append((cur, wstart + 0.9))
    if not blobs: return s
    wi = next((i for i, (b0, b1) in enumerate(blobs) if b1 >= wstart + 0.08), len(blobs) - 1)
    wb0 = blobs[wi][0]
    prev_b1 = blobs[wi-1][1] if wi > 0 else s
    s0 = max(s, wb0 - 0.10, prev_b1 + 0.005)
    if filler_adjacent and wb0 < wstart - 0.05:   # 发声块明显早于词标才可能是粘连uh；≈词标=词自己的浊音头('the'/'but'案)
        g = _glue_skip(rms, zcr, wb0, wtext)
        if g: s0 = g
    return round(s0, 3)
def _refine_end(rms, e, cap=0.30):
    """词尾若仍在发声(whisper 词尾偏早,如 perfect 案)：顺声延伸至静音谷，最多 cap。"""
    if rms is None: return e
    u = e; ext = 0.0
    while ext < cap and rms(u) >= VOICE_TH:
        u += 0.01; ext += 0.01
    return round(u + (0.03 if 0 < ext < cap else 0.0), 3)

# 气口分级：句末给足呼吸，句中压紧
CAP_SENTENCE = 0.55   # 句末（前一个词以 . ? ! 结尾）
CAP_CLAUSE   = 0.32   # 从句/逗号
CAP_INWORD   = 0.18   # 词与词之间的犹豫
MIN_KEEP     = 0.06   # 太碎的片段不单独成段

def _prev_is_filler(words, t):
    """剪点前一个词(全文时间轴)是 filler → 它可能粘着本 span 首词(0915晚 'um the'/'Uh but' 案：
    uh 在 cut_a 外侧，span 内没删过词，旧逻辑不触发粘连判别 → 漏切)。"""
    pw = None
    for w in words:
        if w['end'] <= t + 0.05: pw = w
        else: break
    return bool(pw) and pw['end'] > t - 0.8 and bool(FILLER.match(pw['word']))

def build(words, a, b, drop_filler=True, rms=None, zcr=None):
    ws = [w for w in words if w['start'] >= a - 1e-6 and w['end'] <= b + 1e-6]
    if not ws: return [(a, b)], dict(dropped=0, squeezed=0.0)
    keep, dropped, squeezed = [], 0, 0.0
    prev_end = a
    filler_since = False   # prev_end 之后删过 filler → 该间隙必须声学精修(残响就藏在这)
    first_kept = True      # 段头切点也走精修(段头 pre-roll 同样会带上一句的尾音残响)
    for i, w in enumerate(ws):
        if drop_filler and FILLER.match(w['word']):
            dropped += 1
            filler_since = True
            continue                      # 整词丢弃，前后气口随后统一压
        gap = w['start'] - prev_end
        if gap > 0:
            prevtxt = ws[i-1]['word'] if i else ''
            cap = CAP_SENTENCE if re.search(r'[.?!]\s*$', prevtxt) else (
                  CAP_CLAUSE if re.search(r'[,;:]\s*$', prevtxt) else CAP_INWORD)
            if gap > cap or filler_since or first_kept:
                s0 = _refine_start(rms, max(w['start'] - cap, prev_end), w['start'],
                                   zcr=zcr, wtext=w['word'],
                                   filler_adjacent=filler_since or _prev_is_filler(words, w['start']))
                squeezed += round(max(0.0, gap - (w['start'] - s0)), 3)
                keep.append((s0, w['end']))
            else:
                keep.append((prev_end, w['end']))
        else:
            keep.append((w['start'], w['end']))
        prev_end = w['end']
        filler_since = False
        first_kept = False
    if b > prev_end:
        keep.append((prev_end, min(b, prev_end + CAP_SENTENCE)))
    # 合并相邻/重叠片段
    merged = []
    for s, e in keep:
        if merged and s - merged[-1][1] < 0.012:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    # 每个拼接点的收尾做声学延伸(防 whisper 词尾偏早切词，perfect 案)；钳制不与下一段重叠
    merged = [(s, _refine_end(rms, e)) for s, e in merged]
    merged = [(s, (min(e, merged[i+1][0] - 0.005) if i+1 < len(merged) else e))
              for i, (s, e) in enumerate(merged)]
    merged = [(s, e) for s, e in merged if e - s >= MIN_KEEP]
    return merged, dict(dropped=dropped, squeezed=round(squeezed, 2))

if __name__ == '__main__':
    import sys
    W = json.load(open('whisper.json'))['segments']
    WORDS = [w for s in W for w in s.get('words', [])]
    rows = json.load(open(sys.argv[1] if len(sys.argv) > 1 else 'edl_v3.json'))
    out, tot_in, tot_out = [], 0.0, 0.0
    for r in rows:
        spans, st = build(WORDS, r['cut_a'], r['cut_b'])
        d_in = r['cut_b'] - r['cut_a']; d_out = sum(e - s for s, e in spans)
        tot_in += d_in; tot_out += d_out
        out.append(dict(seg=r['id'], spans=spans, **st))
        print(f"S{r['id']} {d_in:5.1f}s -> {d_out:5.1f}s  片段 {len(spans):3}  删口头禅 {st['dropped']}  压气口 {st['squeezed']}s")
    json.dump(out, open('smooth_spans.json', 'w'))
    print(f"合计 {tot_in:.1f}s -> {tot_out:.1f}s  省 {tot_in-tot_out:.1f}s ({(1-tot_out/tot_in)*100:.0f}%)")
