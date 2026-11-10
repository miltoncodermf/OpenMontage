"""Apple Silicon MLX Text-to-Speech provider with dynamic sample rate and fallback."""

from __future__ import annotations

import logging
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any, Optional

import numpy as np
import soundfile as sf

from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    RetryPolicy,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolStatus,
    ToolTier,
)

logger = logging.getLogger(__name__)


class MlxTTSProvider(BaseTool):
    name = "mlx_tts"
    version = "1.1.0"
    tier = ToolTier.VOICE
    capability = "tts"
    provider = "mlx"
    stability = ToolStability.PRODUCTION
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.LOCAL

    dependencies = []
    agent_skills = ["text-to-speech"]

    capabilities = [
        "text_to_speech",
        "offline_generation",
        "apple_silicon_mlx",
        "dynamic_sample_rate",
        "word_timestamps",
    ]

    supports = {
        "voice_cloning": False,
        "multilingual": True,
        "offline": True,
        "native_audio": True,
        "mlx": True,
    }

    best_for = [
        "high-naturalness local narration on Apple Silicon Mac",
        "offline voiceover with zero API costs",
        "precise word-timestamp alignment",
    ]

    input_schema = {
        "type": "object",
        "required": ["text"],
        "properties": {
            "text": {
                "type": "string",
                "description": "Text to synthesize into speech",
            },
            "voice": {
                "type": "string",
                "default": "af_heart",
                "description": "Voice identifier (e.g. af_heart, af_bella, am_adam)",
            },
            "speed": {
                "type": "number",
                "default": 1.0,
                "description": "Speech speed multiplier",
            },
            "output_path": {
                "type": "string",
                "description": "Target WAV file path",
            },
            "allow_fallback": {
                "type": "boolean",
                "default": True,
                "description": "Whether to allow fallback to Piper TTS if Kokoro MLX fails",
            },
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=4, ram_mb=1024, vram_mb=0, disk_mb=350, network_required=False
    )
    retry_policy = RetryPolicy(max_retries=1, backoff_seconds=1.0)
    idempotency_key_fields = ["text", "voice", "speed"]
    side_effects = ["writes WAV audio to output_path"]
    user_visible_verification = [
        "Listen to generated audio for clarity, natural prosody, and absence of clipping",
        "Verify dynamic sample rate matches audio container metadata",
    ]

    def __init__(self) -> None:
        super().__init__()
        self._kokoro_instance = None

    def get_status(self) -> ToolStatus:
        """Return AVAILABLE if KokoroTTS is importable, DEGRADED if only Piper is present."""
        try:
            from kokoro_mlx import KokoroTTS  # noqa: F401
            return ToolStatus.AVAILABLE
        except Exception:
            pass
        if shutil.which("piper"):
            return ToolStatus.DEGRADED
        return ToolStatus.UNAVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return 0.0

    def _get_kokoro(self):
        if self._kokoro_instance is None:
            from kokoro_mlx import KokoroTTS
            self._kokoro_instance = KokoroTTS.from_pretrained()
        return self._kokoro_instance

    def release_memory(self) -> None:
        """Release MLX model weights and clear Apple Silicon Metal cache."""
        self._kokoro_instance = None
        try:
            import mlx.core as mx
            if hasattr(mx, "clear_cache"):
                mx.clear_cache()
            elif hasattr(mx, "metal") and hasattr(mx.metal, "clear_cache"):
                mx.metal.clear_cache()
        except Exception:
            pass

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        started = time.time()
        text = str(inputs.get("text", "")).strip()
        if not text:
            return ToolResult(success=False, error="Text input cannot be empty")

        voice = str(inputs.get("voice", "af_heart"))
        speed = float(inputs.get("speed", 1.0))
        allow_fallback = bool(inputs.get("allow_fallback", True))
        output_path_str = inputs.get("output_path", "narration.wav")
        output_path = Path(output_path_str).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            kokoro = self._get_kokoro()
            try:
                res = kokoro.generate(text, voice=voice, speed=speed)
            except TypeError:
                res = kokoro.generate(text, voice=voice)

            audio_data = np.asarray(res.audio, dtype=np.float32)
            if audio_data.size == 0:
                raise RuntimeError("KokoroTTS returned an empty audio array")

            sample_rate = int(getattr(res, "sample_rate", 24000))
            sf.write(str(output_path), audio_data, sample_rate)

            duration_s = round(len(audio_data) / float(sample_rate), 3)
            timestamps = self._build_word_timestamps(text, duration_s)
            elapsed = round(time.time() - started, 2)

            return ToolResult(
                success=True,
                data={
                    "provider": "mlx",
                    "model": f"kokoro-mlx/{voice}",
                    "sample_rate": sample_rate,
                    "duration_s": duration_s,
                    "word_count": len(text.split()),
                    "timestamps": timestamps,
                    "output": str(output_path),
                    "format": "wav",
                },
                artifacts=[str(output_path)],
                duration_seconds=elapsed,
                cost_usd=0.0,
                model=voice,
            )
        except Exception as mlx_err:
            logger.warning("Kokoro MLX synthesis failed (%s); allow_fallback=%s", mlx_err, allow_fallback)
            if not allow_fallback:
                return ToolResult(
                    success=False,
                    error=f"Kokoro MLX synthesis failed and allow_fallback=False: {mlx_err}",
                )
            return self._fallback_piper(inputs, str(output_path), started, f"Kokoro MLX fallback ({mlx_err})")

    def _fallback_piper(self, inputs: dict[str, Any], output_path: str, started: float, reason: str) -> ToolResult:
        from tools.audio.piper_tts import PiperTTS

        piper = PiperTTS()
        if piper.get_status() != ToolStatus.AVAILABLE:
            return ToolResult(
                success=False,
                error=f"Both Kokoro MLX and Piper fallback failed: {reason}. Piper status: unavailable",
            )

        piper_inputs = {
            "text": inputs.get("text", ""),
            "output_path": output_path,
            "speed": inputs.get("speed", 1.0),
        }
        res = piper.execute(piper_inputs)
        if not res.success:
            return ToolResult(success=False, error=f"Piper fallback execution failed: {res.error}")

        info = sf.info(output_path)
        sample_rate = int(info.samplerate)
        duration_s = round(float(info.duration), 3)
        timestamps = self._build_word_timestamps(str(inputs.get("text", "")), duration_s)
        elapsed = round(time.time() - started, 2)

        return ToolResult(
            success=True,
            data={
                "provider": "piper_fallback",
                "model": "piper/en_US-lessac-medium",
                "sample_rate": sample_rate,
                "duration_s": duration_s,
                "word_count": len(str(inputs.get("text", "")).split()),
                "timestamps": timestamps,
                "output": str(output_path),
                "format": "wav",
                "fallback_reason": reason,
            },
            artifacts=[str(output_path)],
            duration_seconds=elapsed,
            cost_usd=0.0,
            model="en_US-lessac-medium",
        )

    def _build_word_timestamps(self, text: str, total_duration_s: float) -> list[dict[str, Any]]:
        """Compute punctuation-aware word timestamps aligned to total audio duration."""
        words = text.split()
        if not words or total_duration_s <= 0:
            return []

        total_ms = total_duration_s * 1000.0
        weights: list[float] = []
        pause_weights: list[float] = []

        for idx, word in enumerate(words):
            clean = word.strip(".,!?:;\"'()-—")
            # Base acoustic weight: syllable/character proxy
            char_weight = max(1.5, float(len(clean)))
            # Add trailing pause weight for clause/sentence boundaries (except after the final word)
            pause_w = 0.0
            if idx < len(words) - 1:
                if word.endswith((".", "!", "?")):
                    pause_w = 4.5
                elif word.endswith((",", ";", ":", "—")):
                    pause_w = 2.2
            weights.append(char_weight)
            pause_weights.append(pause_w)

        total_units = sum(weights) + sum(pause_weights)
        ms_per_unit = total_ms / max(1.0, total_units)

        timestamps: list[dict[str, Any]] = []
        current_ms = 0.0

        for word, w_units, p_units in zip(words, weights, pause_weights):
            speak_ms = w_units * ms_per_unit
            gap_ms = p_units * ms_per_unit
            start_ms = round(current_ms, 1)
            end_ms = round(current_ms + speak_ms, 1)
            timestamps.append({
                "word": word,
                "startMs": start_ms,
                "endMs": end_ms,
            })
            current_ms += speak_ms + gap_ms

        if timestamps:
            timestamps[-1]["endMs"] = min(round(total_ms, 1), max(timestamps[-1]["startMs"] + 50.0, round(total_ms, 1)))

        return timestamps
