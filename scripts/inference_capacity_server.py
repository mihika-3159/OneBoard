"""Loopback-only operator sidecar; expose via the approved TLS reverse proxy."""
import os
import subprocess
import hashlib
import json
from functools import lru_cache
from pathlib import Path
from apps.api.services.model_identity import valid_digest
from fastapi import FastAPI
from apps.api.services.inference_resources import available_memory

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/oneboard/capacity")
def capacity():
    available = available_memory()
    try:
        cores = len(os.sched_getaffinity(0))
    except AttributeError:
        cores = os.cpu_count() or 1
    try:
        load = os.getloadavg()[0] / max(1, cores)
    except (OSError, AttributeError):
        load = None
    gpu = None
    try:
        result = subprocess.run(["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
                                capture_output=True, text=True, check=True, timeout=1)
        gpu = min(int(line.strip()) for line in result.stdout.splitlines() if line.strip()) * 1024 * 1024
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return {"accepting": available is not None and load is not None,
            "memory_available_bytes": available, "load_per_cpu": load,
            "accelerator_available_bytes": gpu}


@lru_cache(maxsize=32)
def artifact_digest(path, fingerprint):
    with open(path, "rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verified_models(entries):
    if not isinstance(entries, dict):
        return []
    verified = []
    for name, row in entries.items():
        try:
            expected = row["digest"]
            if not isinstance(name, str) or not name or not valid_digest(expected):
                continue
            path = Path(row["path"]).resolve(strict=True)
            if not path.is_file():
                continue
            before = path.stat()
            fingerprint = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
            actual = artifact_digest(str(path), fingerprint)
            after = path.stat()
            if fingerprint != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                continue
            if actual == expected.removeprefix("sha256:"):
                verified.append({"name": name, "digest": "sha256:" + actual})
        except (OSError, ValueError, TypeError, KeyError):
            continue
    return verified


@app.get("/oneboard/models")
def models():
    try:
        entries = json.loads(os.environ.get("INFERENCE_MODEL_ARTIFACTS", "{}"))
    except ValueError:
        entries = {}
    return {"models": verified_models(entries)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=11460, access_log=False)
