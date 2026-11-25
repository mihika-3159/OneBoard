"""Provider protocol adapters; no user-controlled destinations or automatic paid services."""
import json
from typing import Protocol
from urllib.parse import urlsplit

import httpx

from apps.api.services.inference_stream import read_chat_stream
from apps.api.services.model_identity import matches_pin


class ProviderUnavailable(Exception):
    """An operator-approved provider cannot accept this request."""


class ProviderIdentityUnavailable(ProviderUnavailable):
    """Configured model cannot be identified."""


class ProviderAdapter(Protocol):
    protocol: str

    async def send(self, client, origin, path, payload, emit): ...


class OllamaAdapter:
    protocol = "local_ollama"

    async def send(self, client, origin, path, payload, emit):
        if path == "/api/chat" and emit is not None:
            return await read_chat_stream(client, origin + path, payload, emit)
        return await client.post(origin + path, json=payload)


class CompatibleAdapter:
    """OpenAI-compatible local chat server; never mix embedding spaces."""
    protocol = "local_openai_compatible"

    def __init__(self, pins):
        self.pins = pins

    async def send(self, client, origin, path, payload, emit):
        if path != "/api/chat":
            return httpx.Response(404)
        model = payload["model"]
        if model not in self.pins:
            raise ProviderIdentityUnavailable("Unpinned compatible model")
        pins = await client.get(origin + "/oneboard/models", timeout=2.0)
        try:
            valid = pins.status_code == 200 and matches_pin(pins.json().get("models"), model, self.pins[model])
        except (ValueError, AttributeError, TypeError):
            valid = False
        if not valid:
            raise ProviderIdentityUnavailable("Compatible model identity unavailable")
        request = {"model": model, "messages": payload["messages"],
                   "max_tokens": payload["options"]["num_predict"], "stream": emit is not None}
        if payload.get("format") == "json":
            request["response_format"] = {"type": "json_object"}
        if "temperature" in payload["options"]:
            request["temperature"] = payload["options"]["temperature"]
        url = origin + "/v1/chat/completions"
        if emit is None:
            res = await client.post(url, json=request)
            if res.status_code != 200:
                return res
            body = res.json()
            if len(body.get("choices", [])) != 1:
                raise ValueError("Unexpected compatible completion count")
            choice = body["choices"][0]
            if body.get("model") != model or choice.get("finish_reason") not in ("stop", "length"):
                raise ValueError("Incomplete compatible response")
            return self.normalize(model, choice["message"]["content"], choice["finish_reason"], body.get("usage"))
        parts = []
        size = 0
        finish = None
        usage = None
        async with client.stream("POST", url, json=request) as res:
            if res.status_code != 200:
                return httpx.Response(res.status_code)
            async for line in res.aiter_lines():
                if not line.startswith("data:"):
                    continue
                value = line[5:].strip()
                if value == "[DONE]":
                    if finish not in ("stop", "length"):
                        raise ValueError("Incomplete compatible stream")
                    return self.normalize(model, "".join(parts), finish, usage)
                event = json.loads(value)
                if event.get("error") or event.get("model") != model:
                    raise ValueError("Invalid compatible stream")
                usage = event.get("usage") or usage
                choices = event.get("choices", [])
                if len(choices) > 1:
                    raise ValueError("Unexpected extra completion")
                for choice in choices:
                    if choice.get("index", 0) != 0:
                        raise ValueError("Unexpected extra completion")
                    delta = choice.get("delta", {}).get("content")
                    if delta is not None:
                        if not isinstance(delta, str):
                            raise ValueError("Invalid compatible fragment")
                        size += len(delta)
                        if size > 262144:
                            raise ValueError("Compatible response exceeds bound")
                        parts.append(delta)
                        if delta:
                            await emit(delta)
                    finish = choice.get("finish_reason") or finish
        raise ValueError("Interrupted compatible stream")

    @staticmethod
    def normalize(model, content, finish, usage):
        usage = usage or {}
        return httpx.Response(200, json={"model": model, "message": {"content": content},
            "done": True, "done_reason": finish, "prompt_eval_count": usage.get("prompt_tokens"),
            "eval_count": usage.get("completion_tokens"), "provider_protocol": "local_openai_compatible"})


def is_remote(origin):
    return urlsplit(origin).hostname not in ("localhost", "127.0.0.1", "::1")


def capacity_admitted(data, memory_floor, max_load, accelerator_floor=0):
    if not isinstance(data, dict) or data.get("accepting") is not True:
        return False
    mem, load = data.get("memory_available_bytes"), data.get("load_per_cpu")
    gpu = data.get("accelerator_available_bytes")
    import math
    if type(mem) is not int or mem < memory_floor:
        return False
    if type(load) not in (int, float) or not math.isfinite(load) or not 0 <= load <= max_load:
        return False
    return not accelerator_floor or (type(gpu) is int and gpu >= accelerator_floor)


async def verify_remote_capacity(client, origin, memory_floor, max_load, accelerator_floor=0):
    try:
        response = await client.get(origin + "/oneboard/capacity", timeout=2.0)
        if response.status_code == 200 and capacity_admitted(
            response.json(), memory_floor, max_load, accelerator_floor
        ):
            return
    except (httpx.TransportError, ValueError, TypeError):
        pass
    raise ProviderUnavailable("Remote capacity unavailable")
