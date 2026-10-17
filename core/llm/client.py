"""Local SLM HTTP client for Ollama / llama.cpp servers.

Targets Llama-3.2-3B-Instruct running on localhost with grammar-constrained
JSON decoding and strict latency timeouts.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional
import httpx

# Allow running directly
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.config import DEFAULT_MODEL, DEFAULT_OLLAMA_URL, get_configured_model, save_config


class LLMClientError(Exception):
    """Base exception for LLM inference errors."""


class LLMConnectionError(LLMClientError):
    """Raised when Ollama / llama.cpp server is unreachable."""


class LLMTimeoutError(LLMClientError):
    """Raised when inference exceeds maximum allowable latency."""


class LocalLLMClient:
    """Synchronous & Asynchronous client for local SLM inference."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout_seconds: float = 4.0,
    ):
        self.base_url = (base_url or DEFAULT_OLLAMA_URL).rstrip("/")
        self.model = (model or get_configured_model()).strip()
        self.timeout_seconds = timeout_seconds

    def check_health(self) -> bool:
        """Returns True if local Ollama daemon is reachable."""
        try:
            with httpx.Client(timeout=0.5) as client:
                res = client.get(f"{self.base_url}/api/tags")
                return res.status_code == 200
        except Exception:
            return False

    def get_raw_installed_models(self) -> list[str]:
        """Queries local Ollama /api/tags for actually installed model tags."""
        try:
            with httpx.Client(timeout=1.0) as client:
                res = client.get(f"{self.base_url}/api/tags")
                if res.status_code == 200:
                    data = res.json()
                    return [
                        m.get("name")
                        for m in data.get("models", [])
                        if isinstance(m, dict) and m.get("name")
                    ]
        except Exception:
            pass
        return []

    @staticmethod
    def find_best_matching_model(model_name: str, installed_models: list[str]) -> Optional[str]:
        """Finds closest matching installed model handling tag differences (e.g. :latest vs :3b)."""
        if not model_name or not installed_models:
            return None
        if model_name in installed_models:
            return model_name

        # Prefix match when no tag was specified (e.g. 'llama3.2' -> 'llama3.2:3b')
        if ":" not in model_name:
            prefix = f"{model_name}:"
            for m in installed_models:
                if m.startswith(prefix):
                    return m

        # Generic ':latest' tag match (e.g. 'llama3.2:latest' -> 'llama3.2:3b')
        if model_name.endswith(":latest"):
            base = model_name.split(":")[0]
            for m in installed_models:
                if m.split(":")[0] == base:
                    return m

        return None

    def get_installed_models(self) -> list[str]:
        """Discovers all models currently installed in the local Ollama instance."""
        discovered = self.get_raw_installed_models()

        # If Ollama is running and has models, but active model has tag mismatch (e.g. llama3.2 vs llama3.2:3b),
        # auto-resolve it to the matching installed tag
        if discovered and self.model not in discovered:
            matched = self.find_best_matching_model(self.model, discovered)
            if matched:
                self.model = matched

        # Ensure active model is always selectable even if Ollama is unreachable
        if self.model and self.model not in discovered:
            discovered.insert(0, self.model)
        elif not discovered and self.model:
            discovered = [self.model]

        return discovered

    def set_model(self, model_name: str, persist: bool = True) -> str:
        """Updates the active model identifier in memory and persists to user config."""
        clean_name = model_name.strip()
        if not clean_name:
            raise ValueError("Model name cannot be empty")
        self.model = clean_name
        if persist:
            try:
                save_config({"model": self.model})
            except Exception:
                pass
        return self.model

    def generate_json(self, system_prompt: str, user_prompt: str) -> str:
        """Generates structured JSON using Ollama's grammar-constrained JSON mode.
        
        Uses format='json' to force the local model sampler to output only valid JSON.
        """
        payload: Dict[str, Any] = {
            "model": self.model,
            "prompt": user_prompt,
            "system": system_prompt,
            "stream": False,
            "format": "json",  # Forces llama.cpp JSON grammar mask
            "options": {
                "temperature": 0.1,  # Low temperature for deterministic extraction
                "num_predict": 260,  # Max tokens for full JSON completion
                "top_p": 0.9,
            },
        }

        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                resp = client.post(f"{self.base_url}/api/generate", json=payload)

                # Defensive handling for Ollama 404 (model not found)
                if resp.status_code == 404:
                    err_msg = ""
                    try:
                        err_msg = resp.json().get("error", "")
                    except Exception:
                        err_msg = resp.text

                    # Try auto-recovery: check installed models in Ollama
                    installed = self.get_raw_installed_models()
                    matched = self.find_best_matching_model(self.model, installed)
                    if not matched and DEFAULT_MODEL in installed:
                        matched = DEFAULT_MODEL
                    elif not matched and installed:
                        matched = installed[0]

                    if matched and matched != self.model:
                        # Auto-healed: retry with installed model
                        self.model = matched
                        payload["model"] = matched
                        retry_resp = client.post(f"{self.base_url}/api/generate", json=payload)
                        retry_resp.raise_for_status()
                        return retry_resp.json().get("response", "").strip()

                    raise LLMClientError(
                        f"Ollama returned 404 Not Found for model '{self.model}'. "
                        f"Reason: {err_msg or 'Model not installed'}. "
                        f"Run 'ollama pull {self.model}' in your terminal or choose an installed model."
                    )

                resp.raise_for_status()
                data = resp.json()
                return data.get("response", "").strip()
        except httpx.HTTPStatusError as e:
            err_msg = ""
            try:
                err_msg = e.response.json().get("error", "")
            except Exception:
                err_msg = e.response.text
            raise LLMClientError(
                f"Ollama HTTP {e.response.status_code} error: {err_msg or e}"
            ) from e
        except httpx.ConnectError as e:
            raise LLMConnectionError(
                f"Could not connect to Ollama at {self.base_url}. Ensure 'ollama serve' is running."
            ) from e
        except httpx.TimeoutException as e:
            raise LLMTimeoutError(
                f"LLM inference timed out after {self.timeout_seconds}s (latency budget exceeded)."
            ) from e
        except LLMClientError:
            raise
        except Exception as e:
            raise LLMClientError(f"Unexpected LLM generation error: {e}") from e
