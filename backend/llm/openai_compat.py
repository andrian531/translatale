"""OpenAI-compatible adapter.

Covers OpenAI, OpenRouter, DeepSeek, any custom OpenAI-compatible endpoint and
Ollama (which exposes ``/v1/chat/completions`` locally and needs no API key).
"""

from __future__ import annotations

from typing import Any

import httpx

import config
from llm.base import BaseLLMProvider, LLMError, LLMResponse


class OpenAICompatibleProvider(BaseLLMProvider):
    provider_type = "openai"

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "",
        timeout: float | None = None,
        provider_type: str | None = None,
    ) -> None:
        # ``provider_type`` selects the vendor defaults (base URL, model, auth).
        if provider_type:
            self.provider_type = provider_type
        super().__init__(api_key=api_key, base_url=base_url, timeout=timeout)

    # -- internals --------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if self.provider_type == "openrouter":
            # OpenRouter uses these for attribution; harmless elsewhere.
            headers["HTTP-Referer"] = "http://localhost:5173"
            headers["X-Title"] = "Translatale"
        return headers

    @staticmethod
    def _error_message(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return f"HTTP {response.status_code}: {response.text[:300]}"
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                return f"HTTP {response.status_code}: {error.get('message', error)}"
            if isinstance(error, str):
                return f"HTTP {response.status_code}: {error}"
            if payload.get("message"):
                return f"HTTP {response.status_code}: {payload['message']}"
        return f"HTTP {response.status_code}: {payload}"

    # -- contract ---------------------------------------------------------
    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        model: str | None = None,
        temperature: float = config.DEFAULT_TEMPERATURE,
        max_tokens: int = config.DEFAULT_MAX_TOKENS,
    ) -> LLMResponse:
        self._require_key()
        model_name = (model or self.default_model).strip()

        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload: dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "temperature": float(temperature),
            "max_tokens": int(max_tokens),
            "stream": False,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    self.url("chat/completions"),
                    headers=self._headers(),
                    json=payload,
                )
        except httpx.HTTPError as exc:
            raise LLMError(f"{self.provider_type} request failed: {exc}") from exc

        if response.status_code >= 400:
            raise LLMError(
                f"{self.provider_type} error: {self._error_message(response)}"
            )

        data = response.json()
        choices = data.get("choices") or []
        if not choices:
            raise LLMError(f"{self.provider_type} returned no choices")

        message = choices[0].get("message") or {}
        text = (message.get("content") or "").strip()
        usage = data.get("usage") or {}
        return LLMResponse(
            text=text,
            model=data.get("model", model_name),
            usage={
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "total_tokens": usage.get("total_tokens"),
            },
            raw=data,
        )

    async def test_connection(self, model: str | None = None) -> dict[str, Any]:
        self._require_key()
        model_name = (model or self.default_model).strip()
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    self.url("models"), headers=self._headers()
                )
        except httpx.HTTPError as exc:
            return {"ok": False, "message": f"Connection failed: {exc}", "model": model_name}

        if response.status_code >= 400:
            return {
                "ok": False,
                "message": self._error_message(response),
                "model": model_name,
            }

        available: list[str] = []
        try:
            payload = response.json()
            for item in payload.get("data") or []:
                if isinstance(item, dict) and item.get("id"):
                    available.append(str(item["id"]))
        except ValueError:
            payload = {}

        if available and model_name and model_name not in available:
            return {
                "ok": True,
                "message": (
                    f"Connected, but model '{model_name}' is not in the provider's "
                    f"model list ({len(available)} models available)."
                ),
                "model": model_name,
                "models": available[:50],
            }

        return {
            "ok": True,
            "message": f"Connected. {len(available)} model(s) available.",
            "model": model_name,
            "models": available[:50],
        }
