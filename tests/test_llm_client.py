import pytest

from llm.client import LLMAPIError, LLMClient, LLMResponseError
from llm.config import LLMConfig, LLMConfigurationError


class Message:
    def __init__(self, content: str) -> None:
        self.content = content


class Choice:
    def __init__(self, content: str) -> None:
        self.message = Message(content)
        self.delta = Message(content)


class Response:
    def __init__(self, content: str) -> None:
        self.choices = [Choice(content)]


class Completions:
    def __init__(self, response: object) -> None:
        self.response = response
        self.kwargs = None

    def create(self, **kwargs: object) -> object:
        self.kwargs = kwargs
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class Provider:
    def __init__(self, response: object) -> None:
        self.chat = type("Chat", (), {"completions": Completions(response)})()


def client(response: object) -> tuple[LLMClient, Completions]:
    provider = Provider(response)
    return LLMClient(
        LLMConfig("test-key", "test-model"), provider
    ), provider.chat.completions


def test_generate_sends_both_prompts() -> None:
    llm, calls = client(Response("hello"))
    assert llm.generate("system", "user") == "hello"
    assert calls.kwargs["messages"] == [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "user"},
    ]


def test_generate_stream_yields_chunks() -> None:
    provider = Provider([Response("one"), Response("two")])
    llm = LLMClient(LLMConfig("key", "model"), provider)
    assert list(llm.generate_stream("s", "u")) == ["one", "two"]


def test_generate_json_parses_object() -> None:
    llm, calls = client(Response('{"priority": "high"}'))
    assert llm.generate_json("s", "u") == {"priority": "high"}
    assert calls.kwargs["response_format"] == {"type": "json_object"}


def test_invalid_json_raises() -> None:
    llm, _ = client(Response("not-json"))
    with pytest.raises(LLMResponseError):
        llm.generate_json("s", "u")


def test_api_error_is_wrapped() -> None:
    llm, _ = client(RuntimeError("provider unavailable"))
    with pytest.raises(LLMAPIError, match="request failed"):
        llm.generate("s", "u")


def test_missing_configuration_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    with pytest.raises(LLMConfigurationError, match="LLM_API_KEY"):
        LLMConfig.from_environment()
