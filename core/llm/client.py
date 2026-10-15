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

    def get_installed_models(self) -> list[str]:
        """Discovers all models currently installed in the local Ollama instance."""
        discovered: list[str] = []
        try:
            with httpx.Client(timeout=1.0) as client:
                res = client.get(f"{self.base_url}/api/tags")
                if res.status_code == 200:
                    data = res.json()
                    discovered = [
                        m.get("name")
                        for m in data.get("models", [])
                        if isinstance(m, dict) and m.get("name")
                    ]
        except Exception:
            pass

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
                resp.raise_for_status()
                data = resp.json()
                return data.get("response", "").strip()
        except httpx.ConnectError as e:
            raise LLMConnectionError(
                f"Could not connect to Ollama at {self.base_url}. Ensure 'ollama serve' is running."
            ) from e
        except httpx.TimeoutException as e:
            raise LLMTimeoutError(
                f"LLM inference timed out after {self.timeout_seconds}s (latency budget exceeded)."
            ) from e
        except Exception as e:
            raise LLMClientError(f"Unexpected LLM generation error: {e}") from e
