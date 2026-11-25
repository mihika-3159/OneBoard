"""High-confidence tracked-file secret check; never print detected values.

Checks all current tracked files and, with --history, reachable Git blobs.
Pattern coverage is high-confidence rather than proof of zero credentials.
"""
import argparse
import re
import subprocess
from pathlib import Path

PATTERNS = {
    "private key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----"),
    "GitHub token": re.compile(rb"(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{50,})"),
    "AWS access key": re.compile(rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "OpenAI key": re.compile(rb"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{48,}\b"),
    "age private key": re.compile(rb"AGE-SECRET-KEY-1[0-9A-Z]{55,}"),
    "Google API key": re.compile(rb"\bAIza[0-9A-Za-z_-]{35}\b"),
    "Slack token": re.compile(rb"\bxox[baprs]-[A-Za-z0-9-]{30,}\b"),
    "Stripe live key": re.compile(rb"\b(?:sk|rk)_live_[A-Za-z0-9]{24,}\b"),
    "GitLab token": re.compile(rb"\bglpat-[A-Za-z0-9_-]{20,}\b"),
    "Azure DevOps token": re.compile(rb"\\b[A-Za-z0-9]{52}AZDO[A-Za-z0-9]{28}\\b"),
    "DigitalOcean token": re.compile(rb"\\bdop_v1_[a-f0-9]{64}\\b"),
    "npm access token": re.compile(rb"\\bnpm_[A-Za-z0-9]{36}\\b"),
    "Shopify token": re.compile(rb"\\bshpat_[a-fA-F0-9]{32}\\b"),
    "SendGrid token": re.compile(rb"\\bSG\\.[A-Za-z0-9_-]{22}\\.[A-Za-z0-9_-]{43}\\b"),
    "Hugging Face token": re.compile(rb"\bhf_[A-Za-z0-9]{30,}\b"),
}
def inspect(path,content):
    name=Path(path).name
    hits=[]
    if name==".env" or name.startswith(".env.") and name not in (".env.example",".env.sample",".env.template"):
        hits.append("tracked environment file")
    if name.endswith((".pem",".key",".p12",".pfx")):
        hits.append("tracked key/certificate file")
    hits.extend(label for label,pattern in PATTERNS.items() if pattern.search(content))
    return hits

def history_scan(cwd=None):
    if subprocess.check_output(["git","rev-parse","--is-shallow-repository"],cwd=cwd).strip()!=b"false":
        raise RuntimeError("History scan requires a full checkout")
    raw=subprocess.check_output(["git","rev-list","--objects","--all","--no-object-names"],cwd=cwd)
    ids=raw.splitlines()
    if not ids:
        raise RuntimeError("No reachable Git objects")
    findings=[]
    blobs=0
    proc=subprocess.Popen(["git","cat-file","--batch"],cwd=cwd,stdin=subprocess.PIPE,stdout=subprocess.PIPE)
    try:
        for oid in ids:
            if not re.fullmatch(rb"[a-f0-9]{40,64}",oid):
                raise RuntimeError("Invalid object identifier")
            proc.stdin.write(oid+b"\n")
            proc.stdin.flush()
            header=proc.stdout.readline().split()
            if len(header)!=3 or header[0]!=oid:
                raise RuntimeError("Git history object missing")
            size=int(header[2])
            tail=b""
            labels=set()
            remaining=size
            if header[1]==b"blob":
                blobs+=1
            while remaining:
                chunk=proc.stdout.read(min(65536,remaining))
                if not chunk:
                    raise RuntimeError("Truncated Git object")
                remaining-=len(chunk)
                if header[1] in (b"blob",b"commit",b"tag"):
                    data=tail+chunk
                    labels.update(name for name,pattern in PATTERNS.items() if pattern.search(data))
                    tail=data[-4096:]
            if proc.stdout.read(1)!=b"\n":
                raise RuntimeError("Malformed Git batch response")
            findings.extend((oid.decode(),label) for label in sorted(labels))
        proc.stdin.close()
        if proc.wait(timeout=30)!=0:
            raise RuntimeError("Git object scan failed")
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    history_paths=subprocess.check_output(["git","log","--all","--full-history","-m","--format=","--name-only","-z"],cwd=cwd).split(b"\0")
    for raw_path in set(history_paths):
        path=raw_path.decode("utf-8",errors="replace").strip("\n")
        if not path:
            continue
        for label in inspect(path,b""):
            findings.append(("historical path",label))
    return blobs,findings

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--history",action="store_true")
    args=parser.parse_args()
    tracked=subprocess.check_output(["git","ls-files","-z"]).split(b"\0")
    findings=[]
    for raw in tracked:
        if not raw: continue
        path=Path(raw.decode())
        if path.is_symlink() or not path.is_file(): continue
        for label in inspect(str(path),path.read_bytes()):
            findings.append(("tracked file",label))
    if args.history:
        blobs,historical=history_scan()
        findings.extend(historical)
        print(f"Reachable Git blobs scanned: {blobs}; historical findings: {len(historical)}")
    for object_id,label in findings:
        print(f"SECRET CHECK FAILED: {object_id}: {label}")
    print(f"Tracked files scanned: {len(tracked)-1}; high-confidence findings: {len(findings)}")
    if findings: raise SystemExit(1)
if __name__=="__main__":
    main()
