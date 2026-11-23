"""script_aligner — word timings anchored to the known script (spec D22, §5.8).

ASR (faster-whisper through the existing ``transcriber``) provides real acoustic word times; they
are aligned onto the script tokens (lib/script_alignment.py). Falls back to ``alignment_provider``
(energy heuristic) and says so: ``alignment_method`` is "asr_anchored" or "heuristic".
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import soundfile as sf

from lib.script_alignment import align_narration
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


class ScriptAligner(BaseTool):
    name = "script_aligner"
    version = "1.0.0"
    tier = ToolTier.CORE
    capability = "analysis"
    provider = "faster_whisper"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.LOCAL
    dependencies = []
    agent_skills = ["speech-to-text"]
    fallback_tools = ["alignment_provider"]
    capabilities = ["script_anchored_word_timestamps"]
    best_for = ["caption timings for narration whose exact script is known"]
    not_good_for = ["transcribing unknown speech (use transcriber)"]
    input_schema = {
        "type": "object",
        "required": ["audio_path", "text"],
        "properties": {
            "audio_path": {"type": "string"}, "text": {"type": "string"},
            "model_size": {"type": "string", "default": "base"},
        },
    }
    resource_profile = ResourceProfile(cpu_cores=2, ram_mb=1500, vram_mb=0, disk_mb=200, network_required=False)
    retry_policy = RetryPolicy(max_retries=0)
    install_instructions = "pip install faster-whisper (already used by `transcriber`); on Apple Silicon it runs on CPU."

    def get_status(self) -> ToolStatus:
        try:
            import faster_whisper  # noqa: F401
            return ToolStatus.AVAILABLE
        except ImportError:
            return ToolStatus.DEGRADED  # heuristic fallback only

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return 0.0

    def _asr(self, model_size: str):
        from tools.analysis.transcriber import Transcriber

        def run(audio_path: str) -> list[dict[str, Any]]:
            res = Transcriber().execute({"input_path": audio_path, "model_size": model_size, "language": "en",
                                         "output_dir": str(Path(audio_path).parent / ".asr")})
            if not res.success:
                raise RuntimeError(res.error)
            return res.data["word_timestamps"]
        return run

    def _heuristic(self, audio_path: str, text: str, duration_s: float):
        from tools.audio.alignment_provider import AlignmentProvider

        res = AlignmentProvider().execute({"audio_path": audio_path, "text": text})
        if not res.success:
            raise RuntimeError(res.error)
        return res.data["timestamps"]

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        started = time.time()
        audio = Path(inputs["audio_path"])
        if not audio.is_file():
            return ToolResult(success=False, error=f"audio not found: {audio}")
        info = sf.info(str(audio))
        duration = info.frames / float(info.samplerate)
        try:
            res = align_narration(str(audio), inputs["text"], duration, self._asr(inputs.get("model_size", "base")), self._heuristic)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(success=False, error=f"alignment failed: {exc}")
        return ToolResult(success=True, data={**res, "duration_s": round(duration, 3)}, duration_seconds=round(time.time() - started, 2))
