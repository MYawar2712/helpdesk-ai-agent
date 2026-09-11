"""Environment-based configuration for the LLM client."""

from __future__ import annotations

import os
from dataclasses import dataclass


class LLMConfigurationError(ValueError):
    """Raised when required LLM configuration is missing or invalid."""


@dataclass(frozen=True, slots=True)
class LLMConfig:
    """Runtime settings loaded from environment variables."""

    api_key: str
    model: str
    timeout: float = 30.0
    base_url: str | None = None
    max_output_tokens: int = 512

    @classmethod
    def from_environment(cls) -> LLMConfig:
        api_key = os.getenv("LLM_API_KEY", "").strip()
        model = os.getenv("LLM_MODEL", "qwen-flash").strip()
        if not api_key:
            raise LLMConfigurationError("LLM_API_KEY is not configured")
        if not model:
            raise LLMConfigurationError("LLM_MODEL must not be empty")
        try:
            timeout = float(os.getenv("LLM_TIMEOUT", "30"))
        except ValueError as error:
            raise LLMConfigurationError("LLM_TIMEOUT must be a number") from error
        if timeout <= 0:
            raise LLMConfigurationError("LLM_TIMEOUT must be greater than zero")
        try:
            max_output_tokens = int(os.getenv("LLM_MAX_OUTPUT_TOKENS", "512"))
        except ValueError as error:
            raise LLMConfigurationError(
                "LLM_MAX_OUTPUT_TOKENS must be an integer"
            ) from error
        if max_output_tokens <= 0:
            raise LLMConfigurationError(
                "LLM_MAX_OUTPUT_TOKENS must be greater than zero"
            )
        return cls(
            api_key=api_key,
            model=model,
            timeout=timeout,
            base_url=os.getenv("LLM_BASE_URL") or None,
            max_output_tokens=max_output_tokens,
        )
