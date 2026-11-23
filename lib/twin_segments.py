"""P6: the local twin engine (LivePortrait motion pool + MuseTalk-MLX) productionized for a whole tutorial.

Many presenter segments per tutorial, processed one segment at a time (narration -> alignment -> motion -> lip-sync -> QA -> matte -> preview),
every stage resumable. State lives in ``<run_dir>/run_state.json`` (atomic writes); a stage is skipped on resume only when its input-hash key matches
and its output exists, so a kill at any point costs at most the stage that was running. A segment that fails QA becomes a no-presenter beat
(``fallback``), reported honestly, and the rest of the run continues.

Pure parts (motion planning, state, QA gate evaluation, summary) are unit-tested; the heavy stage workers run in their own process (see
``scripts/twin_tutorial_segments.py``) so memory is returned to the OS between stages.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

import numpy as np

STAGES = ["narration", "align", "motion", "lipsync", "qa", "matte", "preview"]
FPS = 25
CHUNK_S = 6.0  # motion pieces from the pool are about this long
OVERLAP_S = 0.7  # cross-dissolve between pieces
QA_VERSION = "qa-v2"  # bump when gates change so cached verdicts are recomputed
# Owner's pick (variant C2): see scripts/twin_bakeoff_owner.NATURAL_MOUTH.
DEFAULT_MOUTH = {"mask": "lips", "lip_dilate": 0.05, "chin_half": 0.22, "color_match": 1.0}
ALLOWED_NOT_RUN = {"mouth_sync"}  # inconclusive by design for generated mouths (needs an ear); everything else must actually run


# ---------------------------------------------------------------------------------------------------------------- hashing / state


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def key_of(*parts: Any) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(json.dumps(p, sort_keys=True, default=str).encode())
        h.update(b"\x00")
    return h.hexdigest()[:20]


def write_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str))
    os.replace(tmp, path)


class RunState:
    """Checkpoint of one batch run. ``segments[sid]["stages"][stage] = {key, wall_s, peak_footprint_gb, finished}``."""

    def __init__(self, run_dir: Path):
        self.dir = Path(run_dir)
        self.path = self.dir / "run_state.json"
        self.data: dict[str, Any] = json.loads(self.path.read_text()) if self.path.is_file() else {"segments": {}, "events": []}

    def save(self) -> None:
        write_json_atomic(self.path, self.data)

    def seg(self, sid: str) -> dict[str, Any]:
        return self.data["segments"].setdefault(sid, {"stages": {}, "status": "pending"})

    def is_done(self, sid: str, stage: str, key: str, outputs: list[Path]) -> bool:
        rec = self.seg(sid)["stages"].get(stage)
        return bool(rec and rec.get("key") == key and all(Path(o).exists() for o in outputs))

    def mark(self, sid: str, stage: str, key: str, **info: Any) -> None:
        self.seg(sid)["stages"][stage] = {"key": key, "finished": time.strftime("%Y-%m-%dT%H:%M:%S"), **info}
        self.save()

    def event(self, kind: str, **info: Any) -> None:
        self.data["events"].append({"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "kind": kind, **info})
        self.save()


# ---------------------------------------------------------------------------------------------------------------- motion planning


def plan_motion(durations: dict[str, float], clips: list[dict[str, Any]], seed: int = 0, chunk_s: float = CHUNK_S, overlap_s: float = OVERLAP_S,
                boundary_distance: Callable[[str, float, str, float], float] | None = None) -> dict[str, Any]:
    """Pick, per segment, a chain of pieces from the LivePortrait motion pool so beats do not repeat.

    ``clips`` = [{"id", "duration_s"}]. Pieces are taken where the pool has been used least so far (across segments, in order), preferring a start
    whose first frame resembles the previous piece's last frame (``boundary_distance(clip_a, t_a, clip_b, t_b)``) so the cross-dissolve is unnoticeable.
    Deterministic for a given seed. Returns {"segments": {sid: [piece...]}, "reuse": {...}} where reuse says how much of the pool had to be repeated.
    """
    rng = np.random.default_rng(seed)
    res = 10  # usage bins per second
    usage = {c["id"]: np.zeros(int(c["duration_s"] * res) + 1, dtype=np.int32) for c in clips}
    by_id = {c["id"]: c for c in clips}
    plans: dict[str, list[dict[str, Any]]] = {}
    reused_s = total_s = 0.0
    prev: dict[str, Any] | None = None
    for sid, dur in durations.items():
        need = dur + 0.3  # margin so the lip-sync never runs out of frames
        pieces: list[dict[str, Any]] = []
        covered = 0.0
        while covered < need - 1e-6:
            remaining = need - covered + (overlap_s if pieces else 0.0)
            want = min(chunk_s, max(remaining, 1.0))
            if remaining - want < 2.0:  # no tiny trailing piece: absorb the remainder
                want = remaining
            cands: list[tuple[float, str, float, float]] = []
            for c in clips:
                length = min(want, c["duration_s"])
                for start in np.arange(0.0, c["duration_s"] - length + 1e-6, 0.5):
                    seg_use = usage[c["id"]][int(start * res): int((start + length) * res)]
                    cost = float(seg_use.sum()) / res / length  # mean times the segment was already used
                    if prev and prev["clip"] == c["id"] and abs(start - prev["start"]) < length:
                        cost += 0.5  # do not restart inside the piece we just played
                    cands.append((cost, c["id"], float(start), float(length)))
            best = min(x[0] for x in cands)
            tied = [x for x in cands if x[0] <= best + 1e-6]
            if boundary_distance and prev:
                tied.sort(key=lambda x: boundary_distance(prev["clip"], prev["start"] + prev["length"], x[1], x[2]))
                pick = tied[0]
            else:
                pick = tied[int(rng.integers(len(tied)))]
            cost, cid, start, length = pick
            reused_s += min(cost, 1.0) * length
            total_s += length
            usage[cid][int(start * res): int((start + length) * res)] += 1
            prev = {"clip": cid, "start": start, "length": length}
            pieces.append({"clip": cid, "start": round(start, 3), "length": round(length, 3)})
            covered += length - (overlap_s if len(pieces) > 1 else 0.0)
        plans[sid] = pieces
    pool_s = sum(c["duration_s"] for c in clips)
    return {"segments": plans, "reuse": {"pool_seconds": round(pool_s, 1), "seconds_planned": round(total_s, 1),
                                         "seconds_replayed_pct": round(100 * reused_s / max(total_s, 1e-9), 1),
                                         "max_times_any_moment_used": int(max(u.max() for u in usage.values()))}}


def compose_motion(pieces: list[dict[str, Any]], clip_paths: dict[str, Path], dst: Path, duration_s: float, fps: int = FPS, overlap_s: float = OVERLAP_S) -> Path:
    """Cut the planned pieces out of the pool clips and chain them with cross-dissolves into one motion source of ``duration_s``."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    ids = sorted({p["clip"] for p in pieces})
    inputs: list[str] = []
    for cid in ids:
        inputs += ["-i", str(clip_paths[cid])]
    chain, labels = [], []
    for i, p in enumerate(pieces):
        src = ids.index(p["clip"])
        chain.append(f"[{src}:v]trim=start={p['start']:.3f}:duration={p['length']:.3f},setpts=PTS-STARTPTS,fps={fps},format=yuv420p[p{i}]")
        labels.append(f"p{i}")
    prev, acc = labels[0], pieces[0]["length"]
    for i in range(1, len(pieces)):
        ov = min(overlap_s, pieces[i]["length"] / 3, acc / 3)
        out = f"x{i}"
        chain.append(f"[{prev}][{labels[i]}]xfade=transition=fade:duration={ov:.3f}:offset={acc - ov:.3f}[{out}]")
        prev, acc = out, acc + pieces[i]["length"] - ov
    subprocess.run(["ffmpeg", "-y", "-v", "error", *inputs, "-an", "-filter_complex", ";".join(chain), "-map", f"[{prev}]", "-t", f"{duration_s:.3f}",
                    "-c:v", "libx264", "-crf", "14", "-pix_fmt", "yuv420p", str(dst)], check=True, timeout=1800)
    return dst


def gray_boundary_distance(clip_paths: dict[str, Path], size: tuple[int, int] = (64, 36), fps: int = FPS) -> Callable[[str, float, str, float], float]:
    """Frame-difference function between two moments of the pool (tiny gray thumbnails, extracted once)."""
    cache: dict[str, np.ndarray] = {}

    def frames(cid: str) -> np.ndarray:
        if cid not in cache:
            raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(clip_paths[cid]), "-vf", f"fps={fps},scale={size[0]}:{size[1]},format=gray", "-f", "rawvideo", "-"],
                                 capture_output=True, check=True, timeout=600).stdout
            cache[cid] = np.frombuffer(raw, dtype=np.uint8).reshape(-1, size[1] * size[0]).astype(np.float32)
        return cache[cid]

    def dist(ca: str, ta: float, cb: str, tb: float) -> float:
        a, b = frames(ca), frames(cb)
        ia, ib = min(int(ta * fps), len(a) - 1), min(int(tb * fps), len(b) - 1)
        return float(np.abs(a[ia] - b[ib]).mean())

    return dist


# ---------------------------------------------------------------------------------------------------------------- QA gates


def evaluate_qa(report: dict[str, Any]) -> dict[str, Any]:
    """Pass/fail for a segment from a presenter QA report (+ crease_flicker / mouth_opening checks). Not-run checks block, except the
    allowed ``mouth_sync`` inconclusive (flagged in ``warnings``)."""
    checks = report["checks"]
    failed = [k for k, v in checks.items() if v.get("passed") is False]
    not_run = [k for k, v in checks.items() if v.get("passed") is None]
    blocking = [k for k in not_run if k not in ALLOWED_NOT_RUN]
    warnings = [f"{k}: {checks[k].get('status')}" for k in not_run if k in ALLOWED_NOT_RUN]
    passed = not failed and not blocking
    reason = None if passed else "; ".join([*(f"{k} failed" for k in failed), *(f"{k} not run" for k in blocking)])
    return {"passed": passed, "failed": failed, "not_run_blocking": blocking, "warnings": warnings, "reason": reason}


def segment_summary(state: dict[str, Any], durations: dict[str, float]) -> dict[str, Any]:
    """Wall time per stage and per narrated second (for estimating tutorial render times)."""
    per_stage: dict[str, float] = {}
    per_seg: dict[str, Any] = {}
    narrated = 0.0
    for sid, seg in state["segments"].items():
        walls = {st: rec.get("wall_s", 0.0) for st, rec in seg["stages"].items()}
        for st, w in walls.items():
            per_stage[st] = per_stage.get(st, 0.0) + w
        d = durations.get(sid, 0.0)
        narrated += d
        per_seg[sid] = {"status": seg.get("status"), "narrated_s": round(d, 2), "wall_s": round(sum(walls.values()), 1),
                        "wall_per_narrated_s": round(sum(walls.values()) / d, 2) if d else None}
    total = sum(per_stage.values())
    return {"narrated_s": round(narrated, 2), "stage_wall_s": {k: round(v, 1) for k, v in per_stage.items()}, "total_wall_s": round(total, 1),
            "wall_per_narrated_s": round(total / narrated, 2) if narrated else None,
            "stage_per_narrated_s": {k: round(v / narrated, 2) for k, v in per_stage.items()} if narrated else {}, "segments": per_seg}
