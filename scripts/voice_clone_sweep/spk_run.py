import sys,json
import torch
from chatterbox.tts_mlx import ChatterboxTTSMLX
tts=ChatterboxTTSMLX.from_pretrained(device="mps")
spec=json.load(open(sys.argv[1])); E={}
for k,v in spec["clips"].items():
    tts.prepare_conditionals(v,exaggeration=0.5); E[k]=tts.conds.t3.speaker_emb.detach().float().flatten()
res={a:float(torch.dot(E[a],E[b])/(E[a].norm()*E[b].norm())) for a,b in spec["pairs"]}
open(sys.argv[2],"w").write("@@"+json.dumps(res))
