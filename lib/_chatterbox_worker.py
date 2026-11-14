"""Chatterbox worker — runs inside the dedicated chatterbox venv (fix round 1, B7).

chatterbox-mlx pins torch==2.8 / transformers / diffusers, which would break the main environment, so it lives in its own
venv (``<models dir>/chatterbox/venv``) and is driven through JSON over a subprocess (``lib/chatterbox_runner.py``).

What the backend exposes for voice interpolation (verified against chatterbox-mlx 1.3.1, class ``ChatterboxTTSMLX``):
  * ``conds.t3.speaker_emb``  — voice-encoder embedding, tensor (1, 256): INTERPOLATED here (lerp then L2-renormalise);
  * ``conds.gen["embedding"]`` — S3Gen x-vector (1, 192): INTERPOLATED here;
  * ``conds.t3.cond_prompt_speech_tokens`` and ``conds.gen["prompt_token" / "prompt_feat"]`` — acoustic prompt taken
    from the *owner* reference clip: NOT interpolated (they anchor prosody/timbre to the owner), so a blend is
    "owner prompt + blended speaker embeddings", not a full latent mix. This is reported in the output JSON.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path


def _blend(embs: list, weights: list[float]):
    import torch

    acc = sum(w * e.float() for w, e in zip(weights, embs))
    return acc / (acc.norm(dim=-1, keepdim=True) + 1e-8) * embs[0].float().norm(dim=-1, keepdim=True)


def main() -> None:
    spec = json.loads(Path(sys.argv[1]).read_text())
    import soundfile as sf
    import torch
    from chatterbox.tts_mlx import ChatterboxTTSMLX

    t0 = time.time()
    tts = ChatterboxTTSMLX.from_pretrained(device="mps")
    report = {"load_s": round(time.time() - t0, 1), "api": {}, "candidates": []}

    def prep(wav: str, exaggeration: float = 0.5):
        tts.prepare_conditionals(wav, exaggeration=exaggeration)
        c = tts.conds
        return c.t3.speaker_emb.detach().clone(), c.gen["embedding"].detach().clone()

    owner_ve, owner_xv = prep(spec["owner_ref"])
    report["api"] = {"t3.speaker_emb": list(owner_ve.shape), "gen.embedding": list(owner_xv.shape),
                     "interpolated": ["t3.speaker_emb", "gen.embedding"],
                     "not_interpolated": ["t3.cond_prompt_speech_tokens", "gen.prompt_token", "gen.prompt_feat"]}
    donors = {name: prep(path) for name, path in spec["donor_refs"].items()}
    # restore the owner's prompt tokens/features as the base for every candidate
    tts.prepare_conditionals(spec["owner_ref"], exaggeration=0.5)
    base_gen_embedding = tts.conds.gen["embedding"]

    out_dir = Path(spec["out_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    for cand in spec["candidates"]:
        ws = [cand["owner_weight"]] + [d["weight"] for d in cand["donors"]]
        total = sum(ws)
        ws = [w / total for w in ws]
        ves = [owner_ve] + [donors[d["voice"]][0] for d in cand["donors"]]
        xvs = [owner_xv] + [donors[d["voice"]][1] for d in cand["donors"]]
        c = tts.conds
        c.t3.speaker_emb = _blend(ves, ws).to(c.t3.speaker_emb.device).to(c.t3.speaker_emb.dtype)
        c.gen["embedding"] = _blend(xvs, ws).to(base_gen_embedding.device).to(base_gen_embedding.dtype)
        tts._cached_t3_cond_mx = None
        tts._cached_cond_hash = None
        torch.manual_seed(spec.get("seed", 1234))
        t1 = time.time()
        wav = tts.generate(spec["text"], exaggeration=cand["exaggeration"], cfg_weight=cand["cfg"], show_progress=False)
        arr = wav.detach().cpu().numpy().squeeze()
        raw = out_dir / f"{cand['candidate_id']}.raw.wav"
        sf.write(str(raw), arr, int(tts.sr))
        report["candidates"].append({"candidate_id": cand["candidate_id"], "raw": str(raw), "sr": int(tts.sr), "weights": ws,
                                     "seconds": round(time.time() - t1, 1), "audio_s": round(len(arr) / tts.sr, 2)})
        # reset the owner's base embedding for the next candidate
        tts.conds.t3.speaker_emb = owner_ve.to(c.t3.speaker_emb.device).to(c.t3.speaker_emb.dtype)
    Path(spec["out_json"]).write_text(json.dumps(report, indent=2))
    print("DONE")


if __name__ == "__main__":
    main()
