"""Run a reproducible synthetic quality and resource benchmark on configured Ollama."""

import argparse
import asyncio
import json
from pathlib import Path
import statistics
import time

import httpx

from apps.api.services.ollama_gateway import OllamaGateway


CASES = {
    "arithmetic": ("Return a JSON object with only the key answer. What is 19 + 23?", 42),
    "classification": (
        "Classify 'My card was charged twice' as billing, shipping or technical. "
        "Return a JSON object with only the key answer.", "billing",
    ),
    "extraction": (
        "Extract the units from 'Case A has 4 crates and Case B has 9 units.' "
        "Return the number of units in a JSON object with only the key answer.", 9,
    ),
}


def grade(result, expected):
    if result.get("simulated") or result.get("output_limit_reached"):
        return False
    try:
        payload = json.loads(result["content"])
    except (KeyError, TypeError, ValueError):
        return False
    if not isinstance(payload, dict):
        return False
    actual = payload.get("answer")
    return type(actual) is type(expected) and actual == expected


async def loaded_model_resources(base_url, model):
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(f"{base_url}/api/ps")
        response.raise_for_status()
        loaded = response.json()["models"]
    for entry in loaded:
        if entry.get("name") == model:
            return {
                "loaded_bytes": entry.get("size"),
                "vram_bytes": entry.get("size_vram"),
                "digest": entry.get("digest"),
            }
    return None


async def run(model, samples):
    gateway = OllamaGateway()
    runs = []
    for sample in range(samples):
        for name, (question, expected) in CASES.items():
            start = time.monotonic()
            result = await gateway.chat_complete(
                [{"role": "user", "content": question}],
                system_prompt="Follow the request and return a valid JSON object only.",
                model=model,
                format_json=True,
            )
            runs.append({
                "sample": sample + 1,
                "case": name,
                "correct": grade(result, expected),
                "fallback_reason": result.get("fallback_reason"),
                "wall_ms": round((time.monotonic() - start) * 1000, 2),
                "input_tokens": result.get("input_tokens"),
                "output_tokens": result.get("output_tokens"),
                "provider_load_ns": result.get("provider_load_ns"),
                "provider_eval_ns": result.get("provider_eval_ns"),
            })
    resources = await loaded_model_resources(gateway.base_url, model)
    return {
        "model": model,
        "model_resources": resources,
        "correct": sum(row["correct"] for row in runs),
        "total": len(runs),
        "median_wall_ms": statistics.median(row["wall_ms"] for row in runs),
        "max_wall_ms": max(row["wall_ms"] for row in runs),
        "runs": runs,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--samples", type=int, choices=range(1, 11), default=2)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = asyncio.run(run(args.model, args.samples))
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return int(
        any(row["fallback_reason"] for row in report["runs"])
        or report["model_resources"] is None
    )


if __name__ == "__main__":
    raise SystemExit(main())
