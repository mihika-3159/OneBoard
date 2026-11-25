"""Consolidate authenticated GitHub Actions status and artifact metadata for one candidate.

No write permissions or deployment credentials. External signoff remains NO_GO.
"""
import argparse
import json
import os
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request,urlopen
import re

REQUIRED={
 ".github/workflows/verification.yml": {"api-test-evidence","synthetic-finance-provider-review","mandatory-live-test-reports","postgres-required-and-load","dependency-audit-reports","infrastructure-fault-report","measured-capacity-report"},
 ".github/workflows/browser-e2e.yml": {"playwright-results-"+osname+"-"+browser for osname in ("ubuntu-latest","windows-latest","macos-latest") for browser in ("chromium","firefox","webkit")},
 ".github/workflows/container-verification.yml":{"container-build-identities"},
 ".github/workflows/windows-startup.yml":{"oneboard-windows-startup"},
 ".github/workflows/acceptance-evidence.yml":{"oneboard-acceptance-evidence"},
 ".github/workflows/browser-ai-spike.yml":set(),
}
def main():
    p=argparse.ArgumentParser();p.add_argument("--receipt",type=Path,required=True);p.add_argument("--output",type=Path,required=True);a=p.parse_args()
    repository=os.environ["GITHUB_REPOSITORY"];sha=os.environ["CANDIDATE_SHA"];token=os.environ["GITHUB_TOKEN"]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+",repository) or not re.fullmatch(r"[a-f0-9]{40}",sha):raise ValueError("Invalid candidate identity")
    receipt=json.loads(a.receipt.read_text())
    if receipt["commit"]!=os.environ["GITHUB_SHA"] or receipt["run"]!=os.environ["GITHUB_RUN_ID"]:raise ValueError("Release receipt identity mismatch")
    def api(path):
        req=Request("https://api.github.com/repos/"+repository+path,headers={"Authorization":"Bearer "+token,"Accept":"application/vnd.github+json","X-GitHub-Api-Version":"2022-11-28"})
        with urlopen(req,timeout=20) as response:return json.load(response)
    deadline=time.monotonic()+45*60
    while True:
        rows=api("/actions/runs?"+urlencode({"head_sha":sha,"per_page":100}))["workflow_runs"]
        by_path={}
        for row in sorted(rows,key=lambda r:r["id"],reverse=True):
            path=row.get("path","").split("@",1)[0]
            if path in REQUIRED and row.get("head_sha")==sha and row.get("event")==os.environ["GITHUB_EVENT_NAME"]:
                by_path.setdefault(path,row)
        statuses={path:{"id":r["id"],"status":r["status"],"conclusion":r["conclusion"],"url":r.get("html_url"),"head_sha":r["head_sha"]} for path,r in by_path.items()}
        complete=len(by_path)==len(REQUIRED) and all(r["status"]=="completed" for r in by_path.values())
        if complete or time.monotonic()>=deadline:break
        time.sleep(20)
    ok=complete
    for path,r in by_path.items():
        items=api("/actions/runs/"+str(r["id"])+"/artifacts?per_page=100")["artifacts"]
        artifacts={item["name"]:{"id":item["id"],"digest":item.get("digest"),"size_bytes":item["size_in_bytes"]} for item in items if not item["expired"]}
        statuses[path]["artifacts"]=artifacts
        statuses[path]["missing_artifacts"]=sorted(REQUIRED[path]-artifacts.keys())
        ok=ok and r["conclusion"]=="success" and not statuses[path]["missing_artifacts"]
    report={"schema":"oneboard-candidate-acceptance-v1","source_head_sha":sha,"build_commit_sha":os.environ["GITHUB_SHA"],"release_run":os.environ["GITHUB_RUN_ID"],"workflows":statuses,"missing_workflows":sorted(set(REQUIRED)-set(by_path)),"release_receipt":receipt,"engineering_gate":"PASS" if ok else "NO_GO","external_production_gate":"NO_GO","scope":"GitHub Actions source-revision evidence; not an independently signed external attestation"}
    a.output.write_text(json.dumps(report,indent=2,sort_keys=True))
    if not ok:raise SystemExit("Candidate engineering gates are incomplete")
if __name__=="__main__":main()
