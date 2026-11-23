"""Word timings for narration anchored to the KNOWN script text (spec D22, §5.8).

Primary: run ASR with word timestamps (faster-whisper via ``transcriber``) on the narration audio,
align the recognized words to the script tokens with a sequence matcher, and give every script
token a time — matched tokens take the ASR word's time, unmatched tokens (numbers, symbols, ASR
misses) are spread across the gap between their nearest matched neighbours. Honest naming:
``alignment_method == "asr_anchored"`` (the repo has faster-whisper, not whisperX forced alignment).
If confidence is low or ASR is unavailable → energy-heuristic fallback, flagged ``"heuristic"``.
"""

from __future__ import annotations

import difflib
import re
from typing import Any, Callable

MIN_CONFIDENCE = 0.6
_STRIP = re.compile(r"[^\w']+", re.UNICODE)


def norm(token: str) -> str:
    return _STRIP.sub("", token.lower()).strip("'")


def align_script_to_asr(script_text: str, asr_words: list[dict[str, Any]], duration_s: float) -> dict[str, Any]:
    """Return {timestamps:[{word,startMs,endMs}], matched_ratio, method:'asr_anchored'}."""
    script_tokens = script_text.split()
    n = len(script_tokens)
    if n == 0:
        return {"timestamps": [], "matched_ratio": 0.0, "method": "asr_anchored"}
    s_norm = [norm(t) for t in script_tokens]
    a_norm = [norm(str(w["word"])) for w in asr_words]
    starts: list[float | None] = [None] * n
    ends: list[float | None] = [None] * n
    asr_idx: list[int | None] = [None] * n
    sm = difflib.SequenceMatcher(a=s_norm, b=a_norm, autojunk=False)
    matched = 0
    for blk in sm.get_matching_blocks():
        for k in range(blk.size):
            i, j = blk.a + k, blk.b + k
            if s_norm[i]:
                starts[i], ends[i] = float(asr_words[j]["start"]), float(asr_words[j]["end"])
                asr_idx[i] = j
                matched += 1
    # Fill gaps: window = [end of previous anchor (or 0), start of next anchor (or duration)].
    i = 0
    while i < n:
        if starts[i] is not None:
            i += 1
            continue
        j = i
        while j < n and starts[j] is None:
            j += 1
        lo = ends[i - 1] if i > 0 and ends[i - 1] is not None else 0.0
        hi = starts[j] if j < n and starts[j] is not None else float(duration_s)
        # Prefer the ASR words sitting between the neighbouring anchors (e.g. "twenty four" for "24").
        left = (asr_idx[i - 1] + 1) if i > 0 and asr_idx[i - 1] is not None else 0
        right = (asr_idx[j] - 1) if j < n and asr_idx[j] is not None else len(asr_words) - 1
        if left <= right and asr_words:
            lo, hi = max(lo, float(asr_words[left]["start"])), min(hi, float(asr_words[right]["end"]))
        hi = max(hi, lo)
        weights = [max(1, len(s_norm[k]) or 1) for k in range(i, j)]
        total = float(sum(weights))
        t = lo
        for k, w in zip(range(i, j), weights):
            span = (hi - lo) * w / total
            starts[k], ends[k] = t, t + span
            t += span
        i = j
    ts = []
    prev_end = 0.0
    for tok, s, e in zip(script_tokens, starts, ends):
        s = max(float(s), prev_end)          # monotonic, no overlap
        e = max(float(e), s + 0.001)
        e = min(e, float(duration_s) + 0.05)
        ts.append({"word": tok, "startMs": round(s * 1000, 1), "endMs": round(e * 1000, 1)})
        prev_end = min(e, float(duration_s))
    return {"timestamps": ts, "matched_ratio": round(matched / n, 3), "method": "asr_anchored"}


def align_narration(
    audio_path: str,
    text: str,
    duration_s: float,
    asr: Callable[[str], list[dict[str, Any]]] | None,
    heuristic: Callable[[str, str, float], list[dict[str, Any]]],
    min_confidence: float = MIN_CONFIDENCE,
) -> dict[str, Any]:
    """Primary ASR-anchored alignment with an honest, flagged heuristic fallback.

    ``asr(audio_path)`` returns [{word,start,end}] in seconds, or raises when unavailable.
    ``heuristic(audio_path, text, duration_s)`` returns the energy-based timestamps.
    """
    reason = None
    if asr is not None:
        try:
            words = asr(audio_path)
            res = align_script_to_asr(text, words, duration_s)
            if res["matched_ratio"] >= min_confidence:
                return {**res, "alignment_method": "asr_anchored", "confidence": res["matched_ratio"], "fallback_reason": None}
            reason = f"low confidence: only {res['matched_ratio']:.0%} of script tokens matched the ASR words"
        except Exception as exc:  # noqa: BLE001
            reason = f"ASR unavailable: {exc}"
    else:
        reason = "ASR not provided"
    return {"timestamps": heuristic(audio_path, text, duration_s), "alignment_method": "heuristic", "confidence": 0.0,
            "matched_ratio": 0.0, "method": "heuristic", "fallback_reason": reason}
