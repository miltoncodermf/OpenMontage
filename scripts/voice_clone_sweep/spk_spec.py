import sys,json,glob,os
S=sys.argv[1]; T=json.load(open(S+"/sbs/test.json"))
clips={}; pairs=[]
for t in T: clips["real_"+t["id"]]=f'{S}/sbs/real_{t["id"]}.wav'
for p in glob.glob(S+"/sbs/out/*.raw.wav"):
    n=os.path.basename(p)[:-8]; c,sid=n.split("_s",1); sid="s"+sid; clips[f"{c}:{sid}"]=p; pairs.append([f"{c}:{sid}","real_"+sid])
json.dump({"clips":clips,"pairs":pairs},open(S+"/sbs/spk_spec.json","w"))
