"""High-confidence tracked-file secret check; never print detected values.

Checks the checkout, not Git history or arbitrary natural-language credentials.
"""
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

def main():
    tracked=subprocess.check_output(["git","ls-files","-z"]).split(b"\0")
    findings=[]
    for raw in tracked:
        if not raw: continue
        path=Path(raw.decode())
        if path.is_symlink() or not path.is_file(): continue
        # Do not print content. Scan all regular tracked files, including binary.
        for label in inspect(str(path),path.read_bytes()):
            findings.append((str(path),label))
    for path,label in findings:
        print(f"SECRET CHECK FAILED: {path}: {label}")
    print(f"Tracked files scanned: {len(tracked)-1}; high-confidence findings: {len(findings)}")
    if findings: raise SystemExit(1)
if __name__=="__main__":
    main()
