"""Thin client for a local Ollama server.

Deliberately minimal - no SDK, just the two HTTP endpoints we need. That keeps
the dependency surface small and makes it easy to point at any other
OpenAI-incompatible local runtime later by swapping this one file.
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Any

import httpx

from app.config import settings

log = logging.getLogger(__name__)


class OllamaError(Exception):
    """The local model server could not be reached, or refused the request."""


class OllamaClient:
    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        timeout: int | None = None,
    ) -> None:
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self.model = model or settings.ollama_vision_model
        self.timeout = timeout or settings.ollama_timeout_seconds

    def health(self) -> bool:
        """True when the server answers. Used by the worker before it starts."""
        try:
            response = httpx.get(f"{self.base_url}/api/tags", timeout=5)
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    def installed_models(self) -> list[str]:
        try:
            response = httpx.get(f"{self.base_url}/api/tags", timeout=10)
            response.raise_for_status()
            return [m["name"] for m in response.json().get("models", [])]
        except (httpx.HTTPError, KeyError, ValueError):
            return []

    def vision_json(
        self,
        prompt: str,
        image: bytes,
        system: str | None = None,
        schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Send one image and get structured JSON back.

        `format` is set to the JSON schema when one is given, which makes Ollama
        constrain generation with a grammar rather than merely asking nicely.
        That difference is the single biggest accuracy win available here - it
        removes the whole class of "model wrapped the JSON in prose" failures.
        """
        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append(
            {
                "role": "user",
                "content": prompt,
                "images": [base64.b64encode(image).decode("ascii")],
            }
        )

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "format": schema or "json",
            "options": {
                # Reading a receipt is transcription, not writing. Any
                # creativity here is a misread number.
                "temperature": 0,
                "top_p": 0.9,
                "num_predict": 2048,
            },
        }

        try:
            response = httpx.post(
                f"{self.base_url}/api/chat", json=payload, timeout=self.timeout
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise OllamaError(
                f"The model did not answer within {self.timeout}s. On CPU-only "
                f"hardware try a smaller model such as qwen2.5vl:3b."
            ) from exc
        except httpx.HTTPStatusError as exc:
            detail = _error_detail(exc.response)
            if exc.response.status_code == 404:
                raise OllamaError(
                    f"Model {self.model!r} is not installed. Run: "
                    f"docker compose exec ollama ollama pull {self.model}"
                ) from exc
            raise OllamaError(f"Ollama returned {exc.response.status_code}: {detail}") from exc
        except httpx.HTTPError as exc:
            raise OllamaError(
                f"Cannot reach the model server at {self.base_url}: {exc}"
            ) from exc

        body = response.json()
        content = (body.get("message") or {}).get("content", "")
        if not content:
            raise OllamaError("The model returned an empty response")

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            # Grammar-constrained output should make this unreachable, but an
            # older Ollama ignores `format`, so salvage what we can.
            salvaged = _salvage_json(content)
            if salvaged is None:
                log.warning("Unparseable model output: %s", content[:400])
                raise OllamaError("The model did not return valid JSON") from exc
            parsed = salvaged

        if not isinstance(parsed, dict):
            raise OllamaError("The model returned JSON that was not an object")
        return parsed


def _error_detail(response: httpx.Response) -> str:
    try:
        return str(response.json().get("error", response.text))[:300]
    except ValueError:
        return response.text[:300]


def _salvage_json(text: str) -> dict[str, Any] | None:
    """Pull the first balanced JSON object out of a chatty response."""
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    result = json.loads(text[start : index + 1])
                except json.JSONDecodeError:
                    return None
                return result if isinstance(result, dict) else None
    return None
