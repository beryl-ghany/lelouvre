"""Call Gemma locally via Ollama HTTP API (direct from Lelouvre, no extra SDK)."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from .store import Problem


def resolve_gemma_model():
    return (
        os.environ.get("LELOUVRE_GEMMA_MODEL", "").strip()
        or os.environ.get("LELOUVRE_OLLAMA_MODEL", "").strip()
        or "gemma4:e2b"
    )


def resolve_gemma_base_url():
    raw = (
        os.environ.get("LELOUVRE_GEMMA_URL", "").strip()
        or os.environ.get("LELOUVRE_OLLAMA_URL", "").strip()
        or "http://127.0.0.1:11434"
    )
    return raw.rstrip("/").removesuffix("/api/chat").removesuffix("/api/generate")


class GemmaClient:
    """Talks to Gemma through Ollama's /api/chat and /api/tags endpoints."""

    def __init__(self, model=None, base_url=None, transport=None):
        self.base_url = base_url or resolve_gemma_base_url()
        self.model = model or resolve_gemma_model()
        self.transport = transport or self._post

    def status(self):
        try:
            tags = self._get(f"{self.base_url}/api/tags", timeout=5)
            names = [m.get("name", "") for m in tags.get("models", [])]
            return {
                "available": True,
                "model": self.model,
                "base_url": self.base_url,
                "installed_models": names,
                "model_ready": any(self.model in n or n.startswith(self.model) for n in names),
            }
        except Problem as error:
            return {
                "available": False,
                "model": self.model,
                "base_url": self.base_url,
                "error": error.message,
                "installed_models": [],
                "model_ready": False,
            }

    def chat(self, messages, *, json_schema=None, temperature=0, timeout=120, with_meta=False):
        payload = {
            "model": self.model,
            "stream": False,
            "messages": messages,
            "options": {"temperature": temperature},
        }
        if json_schema is not None:
            payload["format"] = json_schema
        result = self.transport(f"{self.base_url}/api/chat", payload, timeout=timeout)
        try:
            content = result["message"]["content"]
        except (KeyError, TypeError) as error:
            raise Problem("Gemma returned an unexpected response shape.", 502, "gemma_invalid") from error
        if not with_meta:
            return content
        duration_ns = result.get("eval_duration") or 0
        meta = {
            "model": self.model,
            "latency_ms": int(duration_ns / 1_000_000) if duration_ns else None,
            "prompt_tokens": result.get("prompt_eval_count"),
            "completion_tokens": result.get("eval_count"),
        }
        return content, meta

    def chat_json(self, messages, json_schema, *, temperature=0, timeout=120, with_meta=False):
        if with_meta:
            content, meta = self.chat(
                messages, json_schema=json_schema, temperature=temperature, timeout=timeout, with_meta=True
            )
            try:
                return json.loads(content), meta
            except json.JSONDecodeError as error:
                raise Problem("Gemma did not return valid JSON.", 502, "gemma_invalid") from error
        content = self.chat(messages, json_schema=json_schema, temperature=temperature, timeout=timeout)
        try:
            return json.loads(content)
        except json.JSONDecodeError as error:
            raise Problem("Gemma did not return valid JSON.", 502, "gemma_invalid") from error

    def _post(self, url, payload, timeout=120):
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read(8 * 1024 * 1024).decode("utf-8"))
        except urllib.error.HTTPError as error:
            body = error.read(4096).decode("utf-8", "replace")
            raise Problem(f"Gemma request failed ({error.code}): {body[:200]}", 502, "gemma_error") from error
        except Exception as error:
            raise Problem(
                "Gemma is unavailable. Start Ollama and run: ollama pull "
                + self.model,
                503,
                "gemma_unavailable",
            ) from error

    def _get(self, url, timeout=10):
        request = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read(2 * 1024 * 1024).decode("utf-8"))
        except Exception as error:
            raise Problem("Cannot reach Ollama at " + self.base_url, 503, "gemma_unavailable") from error
