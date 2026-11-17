"""Local CLI LLM provider adapter for ``agy`` (Antigravity) and ``codex`` (OpenAI Codex)."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import config
from llm.base import BaseLLMProvider, LLMError, LLMResponse

_CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
_MAX_ARGV_PROMPT_CHARS = 24_000

_CODEX_FALLBACK_MODELS: list[str] = [
    "default",
    "gpt-5",
    "gpt-5-mini",
    "o3",
    "o4-mini",
]

_AGY_FALLBACK_MODELS: list[str] = [
    "default",
    "gemini-3.8-flash-medium",
    "gemini-3.8-flash-high",
    "gemini-4-hydrogen-medium",
    "gemini-4-hydrogen-high",
]


def _cli_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["NO_COLOR"] = "1"
    env["FORCE_COLOR"] = "0"
    return env


def resolve_cli_path(engine: str, override_path: str = "") -> str | None:
    """Resolve the executable path for ``agy`` or ``codex``."""
    override = (override_path or "").strip()
    if override:
        candidate = Path(override)
        if candidate.is_file():
            return str(candidate)
        found_override = shutil.which(override)
        if found_override:
            return found_override

    name = "agy" if engine == "agy" else "codex"
    found = shutil.which(name)
    if found:
        return found

    if os.name == "nt":
        local_app = Path(os.environ.get("LOCALAPPDATA", ""))
        candidates = (
            [local_app / "agy" / "bin" / "agy.exe"]
            if engine == "agy"
            else [local_app / "Programs" / "OpenAI" / "Codex" / "bin" / "codex.exe"]
        )
        for path in candidates:
            if path.is_file():
                return str(path)
    return None


def _probe_cli_version(exe: str, timeout: float = 8.0) -> str:
    try:
        proc = subprocess.run(
            [exe, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=_cli_env(),
            creationflags=_CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"error: {exc}"
    output = (proc.stdout or proc.stderr or "").strip()
    return output.splitlines()[0].strip() if output else ""


def describe_cli(engine: str, override_path: str = "") -> dict[str, Any]:
    """Return availability status and executable path for a CLI engine."""
    path = resolve_cli_path(engine, override_path)
    return {
        "available": path is not None,
        "path": path,
    }


def _combine_prompt(prompt: str, system_prompt: str | None) -> str:
    sys_text = (system_prompt or "").strip()
    user_text = (prompt or "").strip()
    if sys_text:
        return f"[SYSTEM INSTRUCTIONS]\n{sys_text}\n\n[USER PROMPT]\n{user_text}"
    return user_text


def _run_agy_sync(
    exe: str,
    full_prompt: str,
    model: str | None,
    timeout: float,
) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        if len(full_prompt) <= _MAX_ARGV_PROMPT_CHARS:
            prompt_arg = full_prompt
        else:
            prompt_file = tmp_dir / "prompt.txt"
            prompt_file.write_text(full_prompt, encoding="utf-8")
            prompt_arg = (
                "Read prompt.txt in the current working directory and follow every "
                "instruction inside it strictly. Output ONLY the exact final result."
            )

        cmd = [
            exe,
            "--output-format",
            "text",
            "--disable-slash-commands",
            "--dangerously-skip-permissions",
        ]
        chosen_model = (model or "").strip()
        if chosen_model and chosen_model.lower() != "default":
            cmd.extend(["--model", chosen_model])
        cmd.append(f"-p={prompt_arg}")

        try:
            proc = subprocess.run(
                cmd,
                cwd=str(tmp_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                env=_cli_env(),
                creationflags=_CREATE_NO_WINDOW,
            )
        except subprocess.TimeoutExpired as exc:
            raise LLMError(f"agy CLI timeout setelah {timeout}s") from exc
        except OSError as exc:
            raise LLMError(f"Gagal menjalankan agy CLI: {exc}") from exc

        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()[-500:]
            raise LLMError(f"agy CLI gagal (exit {proc.returncode}): {err}")
        text = (proc.stdout or "").strip()
        if not text:
            raise LLMError("agy CLI mengembalikan respons kosong")
        return text


def _run_codex_sync(
    exe: str,
    full_prompt: str,
    model: str | None,
    timeout: float,
) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        last_message = tmp_dir / "last.txt"
        cmd = [
            exe,
            "exec",
            "--skip-git-repo-check",
            "--dangerously-bypass-approvals-and-sandbox",
            "-C",
            str(tmp_dir),
            "-o",
            str(last_message),
        ]
        chosen_model = (model or "").strip()
        if chosen_model and chosen_model.lower() != "default":
            cmd.extend(["-m", chosen_model])
        cmd.append("-")

        try:
            proc = subprocess.run(
                cmd,
                input=full_prompt,
                cwd=str(tmp_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                env=_cli_env(),
                creationflags=_CREATE_NO_WINDOW,
            )
        except subprocess.TimeoutExpired as exc:
            raise LLMError(f"codex CLI timeout setelah {timeout}s") from exc
        except OSError as exc:
            raise LLMError(f"Gagal menjalankan codex CLI: {exc}") from exc

        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()[-500:]
            raise LLMError(f"codex CLI gagal (exit {proc.returncode}): {err}")

        if last_message.is_file():
            text = last_message.read_text(encoding="utf-8", errors="replace").strip()
            if text:
                return text

        text = (proc.stdout or "").strip()
        if not text:
            raise LLMError("codex CLI mengembalikan respons kosong")
        return text


def _list_agy_models_sync(exe: str) -> list[str]:
    try:
        proc = subprocess.run(
            [exe, "models"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15.0,
            env=_cli_env(),
            creationflags=_CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return list(_AGY_FALLBACK_MODELS)

    models: list[str] = ["default"]
    seen = {"default"}
    for raw_line in (proc.stdout or "").splitlines():
        line = raw_line.strip()
        if not line or line.lower().startswith("fetching"):
            continue
        slug = line.split("\t", 1)[0].split()[0].strip()
        if slug and slug not in seen:
            seen.add(slug)
            models.append(slug)

    return models if len(models) > 1 else list(_AGY_FALLBACK_MODELS)


def _list_codex_models_sync() -> list[str]:
    cache_path = Path.home() / ".codex" / "models_cache.json"
    models: list[str] = ["default"]
    seen = {"default"}
    if cache_path.is_file():
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8", errors="replace"))
            for item in payload.get("models") or []:
                slug = str(item.get("slug") or "").strip() if isinstance(item, dict) else ""
                if slug and slug not in seen:
                    seen.add(slug)
                    models.append(slug)
        except (OSError, json.JSONDecodeError):
            pass
    return models if len(models) > 1 else list(_CODEX_FALLBACK_MODELS)


class CliLLMProvider(BaseLLMProvider):
    """Adapter that routes LLM calls to local ``agy`` or ``codex`` CLI binaries."""

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "",
        timeout: float | None = None,
        provider_type: str = "agy",
    ) -> None:
        self.provider_type = provider_type
        super().__init__(api_key=api_key, base_url=base_url, timeout=timeout)

    def _resolve_exe(self) -> str:
        exe = resolve_cli_path(self.provider_type, self.base_url)
        if not exe:
            raise LLMError(
                f"{self.provider_type} CLI tidak ditemukan di PATH. "
                f"Pastikan `{self.provider_type}` sudah terinstall dan login."
            )
        return exe

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        model: str | None = None,
        temperature: float = config.DEFAULT_TEMPERATURE,
        max_tokens: int = config.DEFAULT_MAX_TOKENS,
    ) -> LLMResponse:
        del temperature, max_tokens  # CLI tools manage sampling/limits internally.
        exe = self._resolve_exe()
        chosen_model = (model or self.default_model or "default").strip()
        full_prompt = _combine_prompt(prompt, system_prompt)
        timeout = max(float(self.timeout), 180.0)

        if self.provider_type == "agy":
            text = await asyncio.to_thread(_run_agy_sync, exe, full_prompt, chosen_model, timeout)
        elif self.provider_type == "codex":
            text = await asyncio.to_thread(_run_codex_sync, exe, full_prompt, chosen_model, timeout)
        else:
            raise LLMError(f"CLI provider tidak dikenal: {self.provider_type}")

        return LLMResponse(text=text, model=chosen_model)

    async def test_connection(self, model: str | None = None) -> dict[str, Any]:
        del model
        exe = resolve_cli_path(self.provider_type, self.base_url)
        if not exe:
            return {
                "ok": False,
                "message": f"{self.provider_type} CLI tidak ditemukan di PATH.",
            }
        version = await asyncio.to_thread(_probe_cli_version, exe)
        if version.startswith("error:"):
            return {"ok": False, "message": f"{self.provider_type} CLI gagal: {version}"}
        ver_part = f" ({version})" if version else ""
        return {
            "ok": True,
            "message": f"{self.provider_type} CLI ready{ver_part} · {exe}",
        }

    async def list_models(self) -> list[str]:
        exe = self._resolve_exe()
        if self.provider_type == "agy":
            return await asyncio.to_thread(_list_agy_models_sync, exe)
        if self.provider_type == "codex":
            return await asyncio.to_thread(_list_codex_models_sync)
        return ["default"]
