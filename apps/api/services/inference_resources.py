"""Measure local memory headroom and CPU saturation before starting inference."""
import os
from pathlib import Path


def available_memory(root=Path("/")):
    limits = []
    try:
        rows = (root / "proc/meminfo").read_text().splitlines()
        limits.append(next(int(row.split()[1]) * 1024 for row in rows if row.startswith("MemAvailable:")))
    except (OSError, StopIteration, ValueError, IndexError):
        pass
    group = root / "sys/fs/cgroup"
    try:
        ceiling = (group / "memory.max").read_text().strip()
        if ceiling != "max":
            limits.append(int(ceiling) - int((group / "memory.current").read_text()))
    except (OSError, ValueError):
        pass
    return min(limits) if limits else None


def has_headroom(memory_floor, max_load):
    available = available_memory()
    if available is not None and available < memory_floor:
        return False
    try:
        cores = len(os.sched_getaffinity(0))
    except AttributeError:
        cores = os.cpu_count() or 1
    try:
        load = os.getloadavg()[0]
    except (AttributeError, OSError):
        return True
    return load <= cores * max_load
