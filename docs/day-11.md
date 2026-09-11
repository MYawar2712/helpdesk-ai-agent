# Day 11: LLM client

The LLM abstraction keeps provider-specific SDK code out of the helpdesk
business logic. Configure it with environment variables; secrets are never
hard-coded or included in errors:

```powershell
$env:LLM_API_KEY = "your-key"
$env:LLM_MODEL = "qwen-flash"
$env:LLM_BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
$env:LLM_MAX_OUTPUT_TOKENS = "512"
```

Example usage:

```python
from llm.client import LLMClient

client = LLMClient()
answer = client.generate("You are a support assistant.", "My service is down.")
for chunk in client.generate_stream("You are concise.", "Explain the outage steps."):
    print(chunk, end="")
data = client.generate_json("Return a JSON ticket classification.", "Server is down.")
```

`LLMAPIError` represents provider or network failures, `LLMResponseError`
covers empty or malformed responses, and `LLMConfigurationError` identifies
missing or invalid environment configuration. Tests inject a mocked provider
and never make real API calls.
