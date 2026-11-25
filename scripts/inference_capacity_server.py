"""Loopback-only operator sidecar; expose via the approved TLS reverse proxy."""
import os
import subprocess
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=11460, access_log=False)
