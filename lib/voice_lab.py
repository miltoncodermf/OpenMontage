"""Voice design helpers (spec D9, §5.6): recipes, Kokoro blends, polish chain, candidate page.

A *voice profile* is a locked, deterministic recipe: engine + model version + recipe +
polish chain + seed. Kokoro blends are weighted averages of preset style vectors. Chatterbox
cloning/blending is an adapter with an honest availability check (the speaker-embedding
interpolation API must be verified before it is relied on — spec §5.6/§9).
"""

from __future__ import annotations

import hashlib
import html
import json
import subprocess
from pathlib import Path
from typing import Any

POLISH_CHAIN = {
    "name": "om-voice-polish-v1",
    "ffmpeg_filter": (
        "highpass=f=80,"
        "equalizer=f=3200:t=q:w=1.0:g=2.0,"
        "deesser=i=0.4:m=0.5:f=0.5:s=o,"
        "acompressor=threshold=-18dB:ratio=3:attack=10:release=120:makeup=2,"
        "loudnorm=I=-16:TP=-1.5:LRA=11"
    ),
    "steps": ["high-pass 80 Hz", "presence EQ +2 dB @ 3.2 kHz", "de-ess", "light compression 3:1", "loudness normalize -16 LUFS"],
}

# The same tutorial-style paragraph (~20 s) for every candidate so comparison is fair.
SAMPLE_PARAGRAPH = (
    "Today we're going to build something real, step by step. First, I'll show you how the pieces fit together, "
    "then we'll run the code and watch it work. By the end, you'll understand not just what to type, "
    "but why it works, and you'll be able to adapt it to your own project."
)

# Candidate plan: ~8 candidates. Chatterbox ones need the owner's voice recording + the chatterbox backend.
KOKORO_BLENDS = [
    {"candidate_id": "k1_warm_narrator", "voices": [["af_heart", 0.6], ["af_bella", 0.4]], "speed": 1.0},
    {"candidate_id": "k2_clear_guide", "voices": [["af_nicole", 0.5], ["af_heart", 0.5]], "speed": 1.0},
    {"candidate_id": "k3_steady_presenter", "voices": [["am_michael", 0.6], ["am_adam", 0.4]], "speed": 0.98},
    {"candidate_id": "k4_bright_mentor", "voices": [["am_michael", 0.5], ["af_heart", 0.2], ["am_fenrir", 0.3]], "speed": 1.0},
]
CHATTERBOX_BLENDS = [
    {"candidate_id": "c1_owner70", "owner_weight": 0.7, "donors": [{"voice": "am_michael", "weight": 0.3}], "exaggeration": 0.5, "cfg": 0.5, "pitch_semitones": 0.0},
    {"candidate_id": "c2_owner50", "owner_weight": 0.5, "donors": [{"voice": "am_adam", "weight": 0.5}], "exaggeration": 0.5, "cfg": 0.5, "pitch_semitones": 0.0},
    {"candidate_id": "c3_owner30", "owner_weight": 0.3, "donors": [{"voice": "am_michael", "weight": 0.35}, {"voice": "af_heart", "weight": 0.35}], "exaggeration": 0.55, "cfg": 0.45, "pitch_semitones": 0.0},
    {"candidate_id": "c4_owner60_lively", "owner_weight": 0.6, "donors": [{"voice": "am_fenrir", "weight": 0.4}], "exaggeration": 0.7, "cfg": 0.4, "pitch_semitones": 0.5},
]


def validate_kokoro_recipe(rec: dict[str, Any]) -> None:
    voices = rec.get("voices") or []
    if not 1 <= len(voices) <= 3:
        raise ValueError("kokoro recipe needs 1-3 voices")
    total = sum(float(w) for _, w in voices)
    if abs(total - 1.0) > 1e-6:
        raise ValueError(f"kokoro blend weights must sum to 1.0 (got {total})")
    if any(float(w) <= 0 for _, w in voices):
        raise ValueError("blend weights must be positive")
    if not 0.7 <= float(rec.get("speed", 1.0)) <= 1.3:
        raise ValueError("speed must be within 0.7-1.3")


def validate_chatterbox_recipe(rec: dict[str, Any]) -> None:
    donors = rec.get("donors") or []
    total = float(rec["owner_weight"]) + sum(float(d["weight"]) for d in donors)
    if abs(total - 1.0) > 1e-6:
        raise ValueError(f"chatterbox blend weights must sum to 1.0 (got {total})")
    if not 0.0 <= float(rec.get("exaggeration", 0.5)) <= 1.5:
        raise ValueError("exaggeration out of range")


def blend_arrays(arrays: list[Any], weights: list[float]) -> Any:
    """Weighted average of equally-shaped arrays (numpy or mlx)."""
    if len(arrays) != len(weights) or not arrays:
        raise ValueError("arrays/weights mismatch")
    out = arrays[0] * float(weights[0])
    for a, w in zip(arrays[1:], weights[1:]):
        out = out + a * float(w)
    return out


def blend_name(recipe: dict[str, Any]) -> str:
    """Deterministic Kokoro voice name; keeps the first voice's prefix so G2P language inference works."""
    first = recipe["voices"][0][0]
    digest = hashlib.sha256(json.dumps(recipe, sort_keys=True).encode()).hexdigest()[:8]
    return f"{first.split('_')[0]}_blend_{digest}"


def kokoro_synthesize(tts: Any, text: str, recipe: dict[str, Any], sample_rate: int = 24000, seed: int | None = 1234) -> Any:
    """Synthesize with a blended voice by registering the averaged style vector in the voice cache.

    Seeds the MLX RNG so repeated synthesis of the same text is identical up to float32 GPU jitter
    (measured max abs diff ~1e-7); Kokoro is otherwise audibly non-deterministic (vocoder noise).
    """
    validate_kokoro_recipe(recipe)
    if seed is not None:
        import mlx.core as mx

        mx.random.seed(int(seed))
    names = [v for v, _ in recipe["voices"]]
    weights = [float(w) for _, w in recipe["voices"]]
    if len(names) == 1:
        voice = names[0]
    else:
        vm = tts._voices
        voice = blend_name(recipe)
        vm._cache[voice] = blend_arrays([vm.load_voice(n) for n in names], weights)
    return tts.generate(text, voice=voice, speed=float(recipe.get("speed", 1.0)), sample_rate=sample_rate)


def polish(src: Path, dst: Path) -> None:
    """Apply the fixed polish chain (same for every candidate, so comparison is fair)."""
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-af", POLISH_CHAIN["ffmpeg_filter"], "-ar", "48000", str(dst)],
        check=True, timeout=120,
    )


def write_candidates_page(out_dir: Path, candidates: list[dict[str, Any]], title: str = "Pick your presenter voice") -> Path:
    """Local HTML page: one audio player + recipe per candidate. `candidates` items: id, audio (relative), recipe, status."""
    rows = []
    for c in candidates:
        if c.get("status", "ok") == "ok":
            player = f'<audio controls preload="none" src="{html.escape(c["audio"])}"></audio>'
        else:
            player = f'<em>unavailable — {html.escape(str(c.get("reason", "")))}</em>'
        rows.append(
            f'<section><h2>{html.escape(c["id"])}</h2>{player}'
            f'<pre>{html.escape(json.dumps(c["recipe"], indent=2))}</pre></section>'
        )
    page = (
        "<!doctype html><meta charset=utf-8><title>" + html.escape(title) + "</title>"
        "<style>body{font:16px system-ui;max-width:760px;margin:2rem auto;padding:0 1rem}"
        "section{border:1px solid #8884;border-radius:8px;padding:1rem;margin:1rem 0}"
        "pre{background:#8881;padding:.5rem;overflow:auto;font-size:12px}audio{width:100%}</style>"
        f"<h1>{html.escape(title)}</h1><p>All candidates read the same paragraph through the same polish chain "
        f"(<code>{html.escape(POLISH_CHAIN['name'])}</code>). Tell the agent the candidate id you like.</p>"
        "<blockquote>" + html.escape(SAMPLE_PARAGRAPH) + "</blockquote>" + "".join(rows)
    )
    out = out_dir / "index.html"
    out.write_text(page, encoding="utf-8")
    return out


def build_voice_profile(candidate: dict[str, Any], *, model_version: str, seed: int = 1234) -> dict[str, Any]:
    """voice_profile.json content for a picked candidate (locked recipe)."""
    engine = candidate["engine"]
    prof: dict[str, Any] = {
        "version": "1.0", "engine": engine, "model_version": model_version, "candidate_id": candidate["candidate_id"],
        "recipe": candidate["recipe"], "polish_chain": POLISH_CHAIN, "seed": seed,
        "sample": candidate.get("sample"),
        "notes": "Synthesis is seeded: identical for a given text up to float32 GPU jitter (max abs diff ~1e-4, inaudible), not byte-identical.",
    }
    if engine == "chatterbox":
        prof["watermark_note"] = "Chatterbox outputs carry an inaudible Perth watermark (accepted)."
        prof["embedding"] = candidate.get("embedding")
    return prof
