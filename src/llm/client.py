"""Small, provider-isolated client for text and JSON LLM generation."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any, Protocol

from llm.config import LLMConfig


class LLMAPIError(RuntimeError):
    """Raised when the provider cannot complete a request."""


class LLMResponseError(RuntimeError):
    """Raised when the provider returns empty or malformed content."""


class ChatCompletions(Protocol):
    def create(self, **kwargs: Any) -> Any: ...


class Provider(Protocol):
    chat: Any


class LLMClient:
    """Thin wrapper around a chat-completions-compatible provider."""

    def __init__(
        self, config: LLMConfig | None = None, provider: Provider | None = None
    ) -> None:
        self.config = config or LLMConfig.from_environment()
        self._provider = provider or self._build_openai_provider()

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        """Return one complete text response."""

        response = self._request(system_prompt, user_prompt, stream=False)
        try:
            content = response.choices[0].message.content
        except (AttributeError, IndexError, TypeError) as error:
            raise LLMResponseError(
                "LLM response did not contain message content"
            ) from error
        if not isinstance(content, str) or not content.strip():
            raise LLMResponseError("LLM returned an empty response")
        return content

    def generate_stream(self, system_prompt: str, user_prompt: str) -> Iterator[str]:
        """Yield response text chunks as they arrive from the provider."""

        try:
            response = self._request(system_prompt, user_prompt, stream=True)
            for chunk in response:
                content = getattr(chunk.choices[0].delta, "content", None)
                if content:
                    yield content
        except LLMAPIError:
            raise
        except Exception as error:
            raise LLMAPIError("LLM streaming request failed") from error

    def generate_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        """Request and parse a JSON object from the provider."""

        response = self._request(
            system_prompt, user_prompt, stream=False, json_mode=True
        )
        try:
            content = response.choices[0].message.content
            value = json.loads(content)
        except (AttributeError, IndexError, TypeError, json.JSONDecodeError) as error:
            raise LLMResponseError("LLM returned invalid JSON") from error
        if not isinstance(value, dict):
            raise LLMResponseError("LLM JSON response must be an object")
        return value

    def _request(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        stream: bool,
        json_mode: bool = False,
    ) -> Any:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        kwargs: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "stream": stream,
            "timeout": self.config.timeout,
            "max_tokens": self.config.max_output_tokens,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        try:
            return self._provider.chat.completions.create(**kwargs)
        except Exception as error:
            raise LLMAPIError("LLM request failed") from error

    def _build_openai_provider(self) -> Provider:
        try:
            from openai import OpenAI
        except ImportError as error:
            raise LLMAPIError("OpenAI SDK is not installed") from error
        kwargs: dict[str, Any] = {"api_key": self.config.api_key}
        if self.config.base_url:
            kwargs["base_url"] = self.config.base_url
        return OpenAI(**kwargs)
