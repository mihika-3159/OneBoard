"""Fail-closed CI-only lock, artifact, SBOM and acceptance checks."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from xml.etree import ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
def write(path,value):
    Path(path).write_text(json.dumps(value,indent=2,sort_keys=True)+"\n",encoding="utf-8")
def lock_check():
    from packaging.requirements import Requirement
    from packaging.utils import canonicalize_name
    from packaging.version import Version
    lock=(ROOT/"apps/api/requirements.lock").read_text()
    pins={}
    for line in lock.splitlines():
        match=re.match(r"^([A-Za-z0-9_.-]+)==([^ ;\\]+)",line)
        if match:
            key=canonicalize_name(match[1])
            if key in pins: raise ValueError("Duplicate lock pin "+key)
            pins[key]=match[2]
    for line in (ROOT/"apps/api/requirements.txt").read_text().splitlines():
        line=line.split("#",1)[0].strip()
        if not line:continue
        req=Requirement(line)
        if req.marker and not req.marker.evaluate():continue
        key=canonicalize_name(req.name)
        if key not in pins or Version(pins[key]) not in req.specifier:
            raise ValueError("Direct requirement does not match lock: "+key)
    subprocess.run(["python","-m","pip","check"],check=True)
    for workflow in (ROOT/".github/workflows").glob("*.yml"):
        for use in re.findall(r"^\s*(?:-\s*)?uses:\s*([^\s#]+)",workflow.read_text(),re.M):
            if not use.startswith("./") and not re.fullmatch(r"[^@]+@[a-f0-9]{40}",use):
                raise ValueError("Mutable action in "+workflow.name+": "+use)
    return pins
def sbom(out):
    pins=lock_check()
    write(out,{"bomFormat":"CycloneDX","specVersion":"1.5","version":1,
               "components":[{"type":"library","name":name,"version":version,"purl":"pkg:pypi/"+name+"@"+version} for name,version in sorted(pins.items())]})
def coverage_gate(report):
    data=json.loads(Path(report).read_text())
    gates={"apps/api/core/auth.py":60,"apps/api/core/money.py":70,
           "apps/api/services/finance_ledger.py":60,"apps/api/services/account_security.py":60}
    for name,threshold in gates.items():
        item=data["files"].get(name)
        if not item or item["summary"]["percent_covered"]<threshold:
            raise ValueError("Critical coverage below "+str(threshold)+"%: "+name)
def manifest(directory,out):
    directory=Path(directory)
    files={p.relative_to(directory).as_posix():sha(p) for p in sorted(directory.rglob("*")) if p.is_file() and not p.is_symlink()}
    if not files:raise ValueError("No build artifacts")
    write(out,{"schema":"oneboard-build-integrity-v1","commit":os.environ["GITHUB_SHA"],"run":os.environ["GITHUB_RUN_ID"],"files":files})
def verify(directory,receipt):
    directory=Path(directory)
    m=json.loads(Path(receipt).read_text())
    if m["commit"]!=os.environ["GITHUB_SHA"] or m["run"]!=os.environ["GITHUB_RUN_ID"]:raise ValueError("Build identity mismatch")
    if any(p.is_symlink() for p in directory.rglob("*")):raise ValueError("Unexpected symlink")
    actual={p.relative_to(directory).as_posix():sha(p) for p in directory.rglob("*") if p.is_file()}
    if not actual or actual!=m["files"]:raise ValueError("Artifact content mismatch")
def bundle(directory,out):
    directory=Path(directory)
    files=sorted(directory.rglob("*.js"))
    if not files:raise ValueError("Missing frontend JavaScript")
    sizes={p.relative_to(directory).as_posix():p.stat().st_size for p in files}
    total=sum(sizes.values())
    # Conservative absolute ceilings, not a fabricated historic baseline.
    if max(sizes.values())>1_500_000 or total>3_500_000:
        raise ValueError("Frontend JavaScript bundle budget exceeded")
    write(out,{"total_js_bytes":total,"largest_chunk_bytes":max(sizes.values()),"chunks":sizes,"limits":{"total":3500000,"chunk":1500000}})
def aggregate(root,out):
    root=Path(root)
    required=["coverage.json","python-sbom.json","node-sbom.json","bandit.json","frontend-static.json","production-browser.json","build-integrity.json","property-tests.xml","frontend-budget.json"]
    evidence={}
    for name in required:
        matches=list(root.rglob(name))
        if len(matches)!=1 or not matches[0].stat().st_size:raise ValueError("Missing or duplicate evidence "+name)
        p=matches[0]
        if name.endswith(".json"):json.loads(p.read_text())
        else:
            x=ET.parse(p).getroot()
            suites=[x] if x.tag=="testsuite" else x.findall("testsuite")
            if not suites or any(int(s.attrib.get(k,0)) for s in suites for k in ("errors","failures","skipped")):raise ValueError("Incomplete tests "+name)
        evidence[name]={"sha256":sha(p),"bytes":p.stat().st_size}
    write(out,{"schema":"oneboard-batch-p-evidence-v1","commit":os.environ["GITHUB_SHA"],"run":os.environ["GITHUB_RUN_ID"],"evidence":evidence,"external_production_gate":"NO_GO","scope":"disposable CI engineering evidence only; not independent certification"})
def main():
    p=argparse.ArgumentParser()
    p.add_argument("command",choices=["lock","sbom","coverage","manifest","verify","aggregate","bundle"])
    p.add_argument("paths",nargs="*");a=p.parse_args()
    actions={"lock":lock_check,"sbom":sbom,"coverage":coverage_gate,"manifest":manifest,"verify":verify,"aggregate":aggregate,"bundle":bundle}
    actions[a.command](*a.paths)
if __name__=="__main__":main()
