"""Real local Ollama sustained inference resource test; never uses paid APIs."""
import argparse,asyncio,json,os,pathlib,statistics,time
from urllib.parse import urlsplit
from apps.api.services.ollama_gateway import OllamaGateway
from apps.api.core.config import settings
import httpx
def rss_kib():
    # Linux runner: sum resident memory for Ollama and its runner children.
    rss=0
    for entry in pathlib.Path("/proc").iterdir():
        if not entry.name.isdigit():continue
        try:
            name=(entry/"comm").read_text().strip()
            if name not in ("ollama","ollama_llama_server"):continue
            for line in (entry/"status").read_text().splitlines():
                if line.startswith("VmRSS:"):rss+=int(line.split()[1]);break
        except OSError:pass
    return rss
async def soak(model,seconds):
    if os.environ.get("ONEBOARD_CI_INFERENCE_SOAK")!="1" or urlsplit(settings.OLLAMA_BASE_URL).hostname not in ("127.0.0.1","localhost","::1"):
        raise RuntimeError("Explicit disposable loopback inference required")
    gateway=OllamaGateway();started=time.monotonic();runs=[]
    while time.monotonic()-started<seconds:
        begin=time.monotonic()
        result=await gateway.chat_complete([{"role":"user","content":"Return a short sentence describing a synthetic office task."}],model=model)
        if result.get("simulated") or not result.get("content"):raise RuntimeError("Real inference failed during soak: "+str(result.get("fallback_reason")))
        rss=rss_kib()
        runs.append({"wall_ms":round((time.monotonic()-begin)*1000,2),"rss_kib":rss,"output_tokens":result.get("output_tokens") or 0,"elapsed_seconds":round(time.monotonic()-started,2)})
        await asyncio.sleep(2)
    duration=time.monotonic()-started
    assert duration>=seconds and len(runs)>=20 and all(x["rss_kib"]>0 for x in runs)
    warmed=runs[len(runs)//3]["rss_kib"];peak=max(x["rss_kib"] for x in runs)
    assert peak<6*1024*1024 and runs[-1]["rss_kib"]<warmed*1.8+200000
    latencies=sorted(x["wall_ms"] for x in runs)
    return {"duration_seconds":round(duration,2),"genuine_requests":len(runs),"fallbacks":0,"model":model,"median_ms":statistics.median(latencies),"p95_ms":latencies[min(len(latencies)-1,int(.95*len(latencies)))],"peak_ollama_rss_kib":peak,"warm_rss_kib":warmed,"samples":runs,"scope":"disposable local small model; no production capacity claim"}
def main():
    p=argparse.ArgumentParser();p.add_argument("--model",required=True);p.add_argument("--seconds",type=int,default=600);p.add_argument("--output",type=pathlib.Path,required=True);a=p.parse_args()
    if not 300<=a.seconds<=1800:p.error("Require 300-1800 seconds")
    report=asyncio.run(soak(a.model,a.seconds));a.output.write_text(json.dumps(report,indent=2))
    print("INFERENCE_SOAK "+json.dumps({k:v for k,v in report.items() if k!="samples"}))
if __name__=="__main__":main()
