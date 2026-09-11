from pathlib import Path

from llm.client import LLMClient
from llm.config import LLMConfig

PROMPT_DIRECTORY = Path(__file__).parents[1] / "prompts" / "ticket_classifier"
CATEGORIES = {
    "technical",
    "billing",
    "scheduling",
    "warranty",
    "cancellation",
    "general",
}


def test_all_classifier_prompts_exist_and_load() -> None:
    prompts = [
        (PROMPT_DIRECTORY / "v1.md").read_text(encoding="utf-8"),
        (PROMPT_DIRECTORY / "v2.md").read_text(encoding="utf-8"),
        (PROMPT_DIRECTORY / "v3.md").read_text(encoding="utf-8"),
    ]
    assert all(prompts)
    assert all(category in prompt for prompt in prompts for category in CATEGORIES)


def test_prompt_variants_have_distinct_techniques() -> None:
    v1 = (PROMPT_DIRECTORY / "v1.md").read_text(encoding="utf-8")
    v2 = (PROMPT_DIRECTORY / "v2.md").read_text(encoding="utf-8")
    v3 = (PROMPT_DIRECTORY / "v3.md").read_text(encoding="utf-8")
    assert "## Role" in v1
    assert "Customer:" in v2 and "Classification:" in v2
    assert "<role>" in v3 and "<output_format>" in v3


def test_each_prompt_can_be_sent_to_llm_client() -> None:
    class Completions:
        def create(self, **kwargs: object) -> object:
            return type(
                "Response",
                (),
                {
                    "choices": [
                        type(
                            "Choice",
                            (),
                            {
                                "message": type(
                                    "Message", (), {"content": "technical"}
                                )()
                            },
                        )()
                    ]
                },
            )()

    provider = type(
        "Provider", (), {"chat": type("Chat", (), {"completions": Completions()})()}
    )()
    client = LLMClient(LLMConfig("test-key", "test-model"), provider)
    for filename in ("v1.md", "v2.md", "v3.md"):
        prompt = (PROMPT_DIRECTORY / filename).read_text(encoding="utf-8")
        assert client.generate(prompt, "My AC stopped working.") == "technical"
