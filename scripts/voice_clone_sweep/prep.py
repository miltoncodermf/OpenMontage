import sys, json, subprocess
sys.path.insert(0,'.')
import numpy as np, librosa, soundfile as sf
from lib import voice_clean as vc
S=sys.argv[1]; SR=24000
sents=json.load(open(S+"/sbs/sents.json")); byi={o["i"]:o for o in sents}
TEST=[{"id":"s1_start","i":4,"text":"Pack my box with five thousand liquor jugs, then check it twice."},
      {"id":"s2_middle","i":12,"text":"Run PyTest with the verbose flag, then open the JSON report in your editor."},
      {"id":"s3_end","i":34,"text":"When you save a file, the editor tells the language server that something has changed."}]
y,_=librosa.load(S+"/sbs/v2_mono24k.wav",sr=SR)
for t in TEST:
    o=byi[t["i"]]; t["start"]=o["s"]; t["end"]=o["e"]
    a,b=int((o["s"]-0.12)*SR),int((o["e"]+0.12)*SR)
    sf.write(f'{S}/sbs/real_{t["id"]}.wav', y[a:b], SR); t["real_dur"]=round(o["e"]-o["s"],2); t["real_words"]=len(t["text"].split())
json.dump(TEST,open(S+"/sbs/test.json","w"),indent=1)
c=vc.clean(y,SR,rt60=0.3,strength=1.0,reduction_db=8.0); sf.write(S+"/sbs/v2_clean.wav",c,SR)
# candidate reference windows (cleaned audio), away from the test sentences
excl=[(t["start"]-1.5,t["end"]+1.5) for t in TEST]+[(0,11)]
hop=int(0.02*SR); rms=np.array([np.sqrt(np.mean(c[i:i+1024]**2)+1e-12) for i in range(0,len(c)-1024,hop)]); db=20*np.log10(rms+1e-9); voiced=db>np.percentile(db,10)+12; fps=SR/hop
cands=[]
for st in np.arange(11,len(c)/SR-10,1.0):
    if any(st<e and st+10>s for s,e in excl): continue
    seg=voiced[int(st*fps):int((st+10)*fps)]; run=lg=0
    for b_ in seg:
        run=0 if b_ else run+1; lg=max(lg,run)
    if seg.mean()<0.72 or lg/fps>0.9: continue
    f0,vf,_=librosa.pyin(c[int(st*SR):int((st+10)*SR)],fmin=70,fmax=300,sr=SR); f=f0[vf&~np.isnan(f0)]
    if len(f)<50: continue
    cands.append((float(12*np.log2(f.max()/f.min()) if False else np.std(12*np.log2(f/np.median(f)))),float(st),float(seg.mean())))
cands.sort(reverse=True); pick=[]
for sd,st,v in cands:
    if all(abs(st-p[1])>=20 for p in pick): pick.append((sd,st,v))
    if len(pick)==4: break
print("ref windows (f0 std st, start s, voiced):",pick)
def cut(src,dst,start,dur):
    subprocess.run(["ffmpeg","-y","-loglevel","error","-ss",str(start),"-t",str(dur),"-i",src,"-af","highpass=f=80,loudnorm=I=-20:TP=-2:LRA=7","-ar","24000","-ac","1",dst],check=True)
refs={}
for k,(sd,st,v) in enumerate(pick,1):
    cut(S+"/sbs/v2_clean.wav",f"{S}/sbs/ref_w{k}.wav",st,10); refs[f"w{k}"]={"start":st,"f0_std_st":round(sd,2)}
# long refs: baseline window (first 10 s = prompt) + extra windows, no test-sentence overlap
base=S+"/../../../../../../../../Users/nathan/.openmontage/presenter_profiles/ming/raw/working/voice2_ref_clean.wav"
import os; base=os.path.expanduser("~/.openmontage/presenter_profiles/ming/raw/working/voice2_ref_clean.wav")
parts=[base]+[f"{S}/sbs/ref_w{k}.wav" for k in range(1,5)]
for name,n in (("long20",2),("long40",5)):
    arr=[]
    for p in parts[:n]:
        a,_=librosa.load(p,sr=SR); arr+= [a,np.zeros(int(0.3*SR))]
    sf.write(f"{S}/sbs/ref_{name}.wav",np.concatenate(arr),SR)
json.dump(refs,open(S+"/sbs/refs.json","w"))
