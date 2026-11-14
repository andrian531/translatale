"""Anthropic Messages API adapter."""

from __future__ import annotations

from typing import Any

import httpx

import config
from llm.base import BaseLLMProvider, LLMError, LLMResponse

ANTHROPIC_VERSION = "2023-06-01"


class AnthropicProvider(BaseLLMProvider):
    provider_type = "anthropic"

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": ANTHROPIC_VERSION,
        }

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
        return f"HTTP {response.status_code}: {payload}"

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

        payload: dict[str, Any] = {
            "model": model_name,
            "max_tokens": int(max_tokens),
            "temperature": float(temperature),
            "messages": [{"role": "user", "content": prompt}],
        }
        if system_prompt:
            payload["system"] = system_prompt

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    self.url("messages"), headers=self._headers(), json=payload
                )
        except httpx.HTTPError as exc:
            raise LLMError(f"Anthropic request failed: {exc}") from exc

        if response.status_code >= 400:
            raise LLMError(f"Anthropic error: {self._error_message(response)}")

        data = response.json()
        blocks = data.get("content") or []
        text = "".join(
            block.get("text", "")
            for block in blocks
            if isinstance(block, dict) and block.get("type") == "text"
        ).strip()
        usage = data.get("usage") or {}
        return LLMResponse(
            text=text,
            model=data.get("model", model_name),
            usage={
                "prompt_tokens": usage.get("input_tokens"),
                "completion_tokens": usage.get("output_tokens"),
                "total_tokens": (usage.get("input_tokens") or 0)
                + (usage.get("output_tokens") or 0),
            },
            raw=data,
        )

    async def test_connection(self, model: str | None = None) -> dict[str, Any]:
        self._require_key()
        model_name = (model or self.default_model).strip()
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(self.url("models"), headers=self._headers())
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
            pass

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
