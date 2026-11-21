# Voice clone sweep (owner's real read vs Chatterbox)

Used on the owner's `voice_read_v2` to see how close a Chatterbox clone gets to the real voice. All local, $0. `S` = a scratch dir.
Order: `words.json`/`sents.json` (faster-whisper word times of the read) -> `prep.py S` (cut 3 real test sentences, cleaned read, 4 reference
windows that avoid the test sentences, 20 s and 40 s long references) -> `synth.py S` (reference / exaggeration / cfg sweep, per-sentence ASR) ->
`spk_spec.py S` + `spk_run.py` (speaker cosine with Chatterbox's voice encoder, run in the chatterbox venv) -> `score.py S` (speaker, pitch median/range,
DTW pitch-contour correlation, long-term spectrum, centroid, pace; composite score). Chatterbox conditions the acoustic prompt on the first 6 s
(speech tokens) / 10 s (decoder) of the reference, but its speaker embedding averages the WHOLE reference file.
