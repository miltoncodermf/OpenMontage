"""Clean a roomy voice recording before it is used as a Chatterbox reference (numpy/scipy only, no model download).

Chatterbox reproduces the acoustics of its ~10 s reference clip. The owner's read was recorded in an untreated bedroom, so
the clone sounds like "a big empty house". Two classical steps remove most of it:

1. stationary noise reduction: per-bin spectral gate learned from the quietest frames (room tone, fan, mains hum);
2. late-reverb suppression (Lebart/Habets): the reverberant tail in a frame is modelled as an exponentially decayed copy of
   the spectrum ``t_late`` seconds earlier (decay set by ``rt60``) and spectrally subtracted, with a gain floor and
   time/frequency smoothing so it does not turn into "musical noise".

Never modifies the source: callers write cleaned copies under ``raw/working/``.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from scipy.ndimage import uniform_filter
from scipy.signal import istft, stft


def _smooth(g: np.ndarray, t: int = 3, f: int = 3) -> np.ndarray:
    return uniform_filter(g, size=(f, t), mode="nearest")


def denoise(y: np.ndarray, sr: int, reduction_db: float = 12.0, n_fft: int = 1024) -> np.ndarray:
    """Per-bin spectral gate from the quietest 10% of frames."""
    f, t, Z = stft(y, fs=sr, nperseg=n_fft, noverlap=n_fft * 3 // 4)
    mag = np.abs(Z)
    frame_e = (mag ** 2).mean(axis=0)
    quiet = frame_e <= np.percentile(frame_e, 10)
    noise = np.sqrt((mag[:, quiet] ** 2).mean(axis=1, keepdims=True)) if quiet.any() else np.zeros((len(f), 1))
    floor = 10 ** (-reduction_db / 20)
    gain = np.maximum(1.0 - (1.5 * noise / (mag + 1e-9)) ** 2, floor ** 2)
    gain = np.sqrt(_smooth(gain))
    _, out = istft(Z * gain, fs=sr, nperseg=n_fft, noverlap=n_fft * 3 // 4)
    return out[: len(y)].astype(np.float32)


def dereverb(y: np.ndarray, sr: int, rt60: float = 0.6, t_late: float = 0.05, strength: float = 1.0,
             gain_floor_db: float = -14.0, n_fft: int = 1024) -> np.ndarray:
    """Late-reverberation spectral subtraction. ``strength`` scales how much of the modelled tail is removed."""
    hop = n_fft // 4
    f, t, Z = stft(y, fs=sr, nperseg=n_fft, noverlap=n_fft - hop)
    P = np.abs(Z) ** 2
    d = max(1, int(round(t_late * sr / hop)))
    delta = 3 * np.log(10) / rt60
    late = np.zeros_like(P)
    late[:, d:] = np.exp(-2 * delta * t_late) * P[:, :-d]
    # tail energy also accumulates from everything earlier, so smooth the estimate over ~3 frames
    late = uniform_filter(late, size=(1, 3), mode="nearest")
    floor = 10 ** (gain_floor_db / 10)
    gain = np.maximum(1.0 - strength * late / (P + 1e-12), floor)
    gain = np.sqrt(_smooth(gain, t=5, f=3))
    _, out = istft(Z * gain, fs=sr, nperseg=n_fft, noverlap=n_fft - hop)
    return out[: len(y)].astype(np.float32)


def clean(y: np.ndarray, sr: int, *, rt60: float = 0.6, strength: float = 1.0, reduction_db: float = 12.0) -> np.ndarray:
    return dereverb(denoise(y, sr, reduction_db=reduction_db), sr, rt60=rt60, strength=strength)


def pick_window(y: np.ndarray, sr: int, seconds: float = 10.0, step: float = 1.0) -> tuple[float, dict[str, Any]]:
    """Best ``seconds`` window of an already-cleaned read: most continuous speech, cleanest pauses, no clipping."""
    from lib import voice_metrics as vm

    hop = int(0.02 * sr)
    rms = np.array([np.sqrt(np.mean(y[i:i + 1024] ** 2) + 1e-12) for i in range(0, len(y) - 1024, hop)])
    db = 20 * np.log10(rms + 1e-9)
    voiced = db > np.percentile(db, 10) + 12
    fps = sr / hop
    best: tuple[float, float, dict[str, Any]] | None = None
    for st in np.arange(0, len(y) / sr - seconds, step):
        seg = y[int(st * sr):int((st + seconds) * sr)]
        if np.abs(seg).max() > 0.95:
            continue
        v = float(voiced[int(st * fps):int((st + seconds) * fps)].mean())
        run = longest = 0
        for b in voiced[int(st * fps):int((st + seconds) * fps)]:
            run = 0 if b else run + 1
            longest = max(longest, run)
        t = vm.tail(seg, sr)
        score = v - 0.15 * (longest / fps) + (0.004 * (t["pause_floor_db"] or 0) * -1 if False else 0)
        if best is None or score > best[0]:
            best = (score, float(st), {"voiced": round(v, 3), "longest_pause_s": round(longest / fps, 2), **t})
    if best is None:
        return 0.0, {}
    return best[1], best[2]


# Corrective EQ for a recording that is boomy below ~600 Hz and dark above (measured on the owner's read: speech energy
# 10 dB heavier in 60-640 Hz than a dry voice, falling steeply above 640 Hz).
TILT_EQ = "lowshelf=f=200:g=-4,equalizer=f=420:t=q:w=1.0:g=-3,equalizer=f=900:t=q:w=1.0:g=-1.5,equalizer=f=3500:t=q:w=1.0:g=3"


def make_clean_reference(raw, dst, *, seconds: float = 10.0, tilt_eq: bool = False, rt60: float = 0.7, strength: float = 1.5,
                         reduction_db: float = 12.0) -> dict[str, Any]:
    """Cleaned ~10 s reference cut from the whole read: denoise + de-reverb the full read, pick the best window of the
    CLEANED audio, optionally apply the corrective tilt EQ, level to -20 LUFS. Writes only ``dst`` (mono 24 kHz wav)."""
    import subprocess
    import tempfile
    from pathlib import Path

    import librosa
    import soundfile as sf

    raw, dst = Path(raw), Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        mono = Path(td) / "mono.wav"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw), "-ac", "1", "-ar", "24000", str(mono)], check=True, timeout=300)
        y, sr = librosa.load(str(mono), sr=24000)
        c = clean(y, sr, rt60=rt60, strength=strength, reduction_db=reduction_db)
        start, info = pick_window(c, sr, seconds)
        cut = Path(td) / "cut.wav"
        sf.write(str(cut), c[int(start * sr):int((start + seconds) * sr)], sr)
        af = "highpass=f=80," + (TILT_EQ + "," if tilt_eq else "") + "loudnorm=I=-20:TP=-2:LRA=7"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(cut), "-af", af, "-ar", "24000", "-ac", "1", str(dst)],
                       check=True, timeout=120)
    dst.chmod(0o600)
    return {"file": dst.name, "start_s": round(start, 2), "seconds": seconds, "denoise_db": reduction_db, "rt60": rt60,
            "strength": strength, "tilt_eq": tilt_eq, **info}
