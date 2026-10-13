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

DEFAULT_OLLAMA_URL = os.getenv("OLLAMA_HOST", "http://localhost:11434")
DEFAULT_MODEL = os.getenv("WAYFINDER_MODEL", "llama3.2:3b")


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
        base_url: str = DEFAULT_OLLAMA_URL,
        model: str = DEFAULT_MODEL,
        timeout_seconds: float = 4.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds

    def check_health(self) -> bool:
        """Returns True if local Ollama daemon is reachable."""
        try:
            with httpx.Client(timeout=0.5) as client:
                res = client.get(f"{self.base_url}/api/tags")
                return res.status_code == 200
        except Exception:
            return False

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
