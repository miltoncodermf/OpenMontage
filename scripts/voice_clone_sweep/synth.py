import sys, json, time, shutil
sys.path.insert(0,'.')
from pathlib import Path
from lib import chatterbox_runner as cr, voice_lab as vl
from lib.heavy_lock import heavy_job
S=Path(sys.argv[1]); only_cfgs=set(sys.argv[2].split(",")) if len(sys.argv)>2 else None
T=json.load(open(S/"sbs/test.json")); texts=[t["text"] for t in T]
home=Path.home()/".openmontage/presenter_profiles/ming"
def cand(cid,e=0.5,c=0.5): return {"candidate_id":cid,"owner_weight":1.0,"donors":[],"exaggeration":e,"cfg":c,"pitch_semitones":0.0}
plan=[  # (reference, [candidates])
 (str(home/"raw/working/voice2_ref_clean.wav"),[cand("base"),cand("e035",e=0.35),cand("e070",e=0.7),cand("c030",c=0.3),cand("c070",c=0.7)]),
 (str(S/"sbs/ref_w1.wav"),[cand("w1")]),(str(S/"sbs/ref_w2.wav"),[cand("w2")]),(str(S/"sbs/ref_w3.wav"),[cand("w3")]),(str(S/"sbs/ref_w4.wav"),[cand("w4")]),
 (str(S/"sbs/ref_long20.wav"),[cand("long20")]),(str(S/"sbs/ref_long40.wav"),[cand("long40")]),
]
extra=json.load(open(S/"sbs/extra_plan.json")) if (S/"sbs/extra_plan.json").exists() and only_cfgs and "extra" in only_cfgs else None
if extra: plan=[(e["ref"],[cand(c["id"],c["e"],c["c"]) for c in e["cands"]]) for e in extra]
out=S/"sbs/out"; out.mkdir(exist_ok=True); report={}
with heavy_job("voice_sweep",wait=1800):
    for ref,cands in plan:
        t0=time.time()
        rep=cr.synthesize(ref,{},cands,texts,S/"sbs/tmp",seed=1234)
        for cr_ in rep["candidates"]:
            cid=cr_["candidate_id"]; c=next(x for x in cands if x["candidate_id"]==cid)
            for ch in cr_["chunks"]:
                idx=ch["idx"]; raw=Path(ch["raw"]); cov=vl.asr_coverage(raw,texts[idx]); ok=vl.chunk_ok(texts[idx],cov["heard"],cov["coverage"]); take=1
                while not ok and take<3:
                    take+=1; rr=cr.synthesize(ref,{},[c],texts,S/f"sbs/tmp_r{take}",seed=1234,only=[f"{cid}:{idx}"],seeds={f"{cid}:{idx}":1234+idx+100*take})
                    raw=Path(rr["candidates"][0]["chunks"][0]["raw"]); cov=vl.asr_coverage(raw,texts[idx]); ok=vl.chunk_ok(texts[idx],cov["heard"],cov["coverage"])
                dst=out/f"{cid}_{T[idx]['id']}.raw.wav"; shutil.copy(raw,dst)
                report[f"{cid}:{T[idx]['id']}"]={"takes":take,"ok":bool(ok),"coverage":cov["coverage"],"heard":cov["heard"]}
        print(ref.split("/")[-1],"done",round(time.time()-t0),"s",flush=True)
        shutil.rmtree(S/"sbs/tmp",ignore_errors=True)
old=json.load(open(S/"sbs/synth_report.json")) if (S/"sbs/synth_report.json").exists() else {}
old.update(report); json.dump(old,open(S/"sbs/synth_report.json","w"),indent=1)
