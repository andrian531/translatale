"""Google Gemini adapter (REST ``generateContent``)."""

from __future__ import annotations

from typing import Any

import httpx

import config
from llm.base import BaseLLMProvider, LLMError, LLMResponse


class GeminiProvider(BaseLLMProvider):
    provider_type = "gemini"

    # -- internals --------------------------------------------------------
    def _endpoint(self, model: str, action: str) -> str:
        model = (model or self.default_model).strip()
        if model.startswith("models/"):
            model = model[len("models/") :]
        return self.url(f"models/{model}:{action}")

    @staticmethod
    def _error_message(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return f"HTTP {response.status_code}: {response.text[:300]}"
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict):
            return f"HTTP {response.status_code}: {error.get('message', error)}"
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

        payload: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": float(temperature),
                "maxOutputTokens": int(max_tokens),
            },
        }
        if system_prompt:
            payload["systemInstruction"] = {"parts": [{"text": system_prompt}]}

        url = self._endpoint(model_name, "generateContent")
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    url, params={"key": self.api_key}, json=payload
                )
        except httpx.HTTPError as exc:
            raise LLMError(f"Gemini request failed: {exc}") from exc

        if response.status_code >= 400:
            raise LLMError(f"Gemini error: {self._error_message(response)}")

        data = response.json()
        candidates = data.get("candidates") or []
        if not candidates:
            blocked = (data.get("promptFeedback") or {}).get("blockReason")
            raise LLMError(
                f"Gemini returned no candidates{f' (blocked: {blocked})' if blocked else ''}"
            )

        parts = (candidates[0].get("content") or {}).get("parts") or []
        text = "".join(part.get("text", "") for part in parts).strip()
        usage = data.get("usageMetadata") or {}
        return LLMResponse(
            text=text,
            model=data.get("modelVersion", model_name),
            usage={
                "prompt_tokens": usage.get("promptTokenCount"),
                "completion_tokens": usage.get("candidatesTokenCount"),
                "total_tokens": usage.get("totalTokenCount"),
            },
            raw=data,
        )

    async def test_connection(self, model: str | None = None) -> dict[str, Any]:
        self._require_key()
        model_name = (model or self.default_model).strip()
        url = self._endpoint(model_name, "")
        url = url.rstrip(":")
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url, params={"key": self.api_key})
        except httpx.HTTPError as exc:
            return {"ok": False, "message": f"Connection failed: {exc}", "model": model_name}

        if response.status_code >= 400:
            return {
                "ok": False,
                "message": self._error_message(response),
                "model": model_name,
            }
        return {
            "ok": True,
            "message": f"Connected. Model '{model_name}' is reachable.",
            "model": model_name,
        }
