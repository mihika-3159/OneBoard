"""Conservative resource planning from measured disposable workload reports."""
import argparse,json,math
from pathlib import Path
def plan(load,inference,workers,db_connections,memory_mib,pool_size=5,overflow=5):
    if not 1<=workers<=4 or not 1<=db_connections<=1000 or not 128<=memory_mib<=1048576 or not 1<=pool_size<=32 or not 0<=overflow<=16:raise ValueError("Invalid capacity inputs")
    if load["seconds"]<300 or load["unexpected_errors"]!=0 or inference["duration_seconds"]<300 or inference["fallbacks"]!=0:raise ValueError("Sustained clean measurements required")
    api_peak=float(load["peak_api_rss_kib"])/1024
    infer_peak=float(inference["peak_ollama_rss_kib"])/1024
    if not all(math.isfinite(x) and x>0 for x in (api_peak,infer_peak,load["requests"],inference["genuine_requests"])):raise ValueError("Invalid measurements")
    measured_workers=int(load["workers"])
    if not 1<=measured_workers<=4:raise ValueError("Invalid measured worker count")
    # 30% margin plus fixed OS/DB reserve; explicit planning heuristic, not a
    # measured scaling curve. Do not extrapolate request throughput.
    estimated=math.ceil(1.3*(api_peak*workers/measured_workers+infer_peak)+1024)
    connections=workers*(pool_size+overflow)+5
    return {"measured":{"api_requests_per_second":round(load["requests"]/load["seconds"],2),"api_p95_ms":load["p95_ms"],"inference_requests_per_minute":round(60*inference["genuine_requests"]/inference["duration_seconds"],2),"inference_p95_ms":inference["p95_ms"],"api_peak_mib":round(api_peak,1),"inference_peak_mib":round(infer_peak,1)},
        "planning":{"workers":workers,"database_connections_required":connections,"database_connections_available":db_connections,"memory_mib_required_heuristic":estimated,"memory_mib_available":memory_mib,
        "fits_configured_budget":connections<=db_connections and estimated<=memory_mib},
        "limitations":"Synthetic small-model CI measurements; memory estimate includes 30% margin and 1GiB OS/DB reserve; no throughput extrapolation or SLA."}
def main():
    p=argparse.ArgumentParser();p.add_argument("--http-load",type=Path,required=True);p.add_argument("--inference",type=Path,required=True);p.add_argument("--workers",type=int,default=2);p.add_argument("--db-connections",type=int,default=40);p.add_argument("--memory-mib",type=int,default=8192);p.add_argument("--output",type=Path,required=True);a=p.parse_args()
    result=plan(json.loads(a.http_load.read_text()),json.loads(a.inference.read_text()),a.workers,a.db_connections,a.memory_mib)
    a.output.write_text(json.dumps(result,indent=2));print(json.dumps(result))
if __name__=="__main__":main()
