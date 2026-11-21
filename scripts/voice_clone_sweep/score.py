import sys, json, glob, os, subprocess
sys.path.insert(0,'.')
import numpy as np, librosa
from scipy.signal import welch
S=sys.argv[1]; SR=24000
T=json.load(open(S+"/sbs/test.json"))
def load(p): y,_=librosa.load(p,sr=SR); return y
def f0s(y):
    f0,vf,_=librosa.pyin(y,fmin=70,fmax=300,sr=SR); return f0, vf&~np.isnan(f0)
def feats(y):
    f0,v=f0s(y); f=f0[v]; st=12*np.log2(f/55.0)
    ff,p=welch(y,fs=SR,nperseg=2048); m=(ff>=100)&(ff<8000)
    edges=np.geomspace(100,8000,25); ltas=np.array([10*np.log10(p[(ff>=a)&(ff<b)].sum()+1e-14) for a,b in zip(edges[:-1],edges[1:])]); ltas-=ltas.mean()
    cen=float((ff[(ff>=80)&(ff<10240)]*p[(ff>=80)&(ff<10240)]).sum()/p[(ff>=80)&(ff<10240)].sum())
    return {"st":st,"f0_med":float(np.median(f)),"range_st":float(np.percentile(st,90)-np.percentile(st,10)),"ltas":ltas,"centroid":cen,"dur":len(y)/SR}
def contour_corr(a,b):
    a=(a-a.mean())/(a.std()+1e-9); b=(b-b.mean())/(b.std()+1e-9)
    D,wp=librosa.sequence.dtw(a[None,:],b[None,:],metric="euclidean"); wp=wp[::-1]
    x=np.array([a[i] for i,_ in wp]); y=np.array([b[j] for _,j in wp]); return float(np.corrcoef(x,y)[0,1])
real={t["id"]:feats(load(f'{S}/sbs/real_{t["id"]}.wav')) for t in T}
cfgs=sorted({os.path.basename(p).split("_s")[0] for p in glob.glob(S+"/sbs/out/*.raw.wav")})
spk={}
if os.path.exists(S+"/sbs/spk.json"):
    spk=json.load(open(S+"/sbs/spk.json"))
rows={}
for c in cfgs:
    per=[]
    for t in T:
        p=f'{S}/sbs/out/{c}_{t["id"]}.raw.wav'
        if not os.path.exists(p): continue
        g=feats(load(p)); r=real[t["id"]]
        d={"pitch_med_diff_st":12*np.log2(g["f0_med"]/r["f0_med"]),"range_diff_st":g["range_st"]-r["range_st"],"ltas_mad_db":float(np.abs(g["ltas"]-r["ltas"]).mean()),
           "centroid_ratio":g["centroid"]/r["centroid"],"dur_ratio":g["dur"]/r["dur"],"contour_r":contour_corr(g["st"],r["st"]),"f0_med":g["f0_med"],"real_f0_med":r["f0_med"],
           "spk":spk.get(f'{c}:{t["id"]}')}
        per.append(d)
    avg={k:float(np.mean([d[k] for d in per if d[k] is not None])) if any(d[k] is not None for d in per) else None for k in per[0]}
    avg["abs_pitch_diff"]=float(np.mean([abs(d["pitch_med_diff_st"]) for d in per])); avg["abs_range_diff"]=float(np.mean([abs(d["range_diff_st"]) for d in per]))
    s=avg["spk"]
    avg["score"]=None if s is None else round(0.40*s+0.20*max(0,avg["contour_r"])+0.15*(1-min(1,avg["abs_pitch_diff"]/2))+0.10*(1-min(1,avg["abs_range_diff"]/3))+0.15*(1-min(1,avg["ltas_mad_db"]/6)),4)
    rows[c]=avg
json.dump(rows,open(S+"/sbs/scores.json","w"),indent=1)
print("%-8s %6s %6s %7s %7s %6s %6s %6s %6s"%("cfg","spk","contR","pitchΔst","rangeΔst","ltasdB","cenRat","durRat","SCORE"))
for c,a in sorted(rows.items(),key=lambda kv:-(kv[1]["score"] or 0)):
    print("%-8s %6s %6.3f %+7.2f %+7.2f %6.2f %6.2f %6.2f %6s"%(c,("%.3f"%a["spk"]) if a["spk"] is not None else "-",a["contour_r"],a["pitch_med_diff_st"],a["range_diff_st"],a["ltas_mad_db"],a["centroid_ratio"],a["dur_ratio"],a["score"]))
