"""One-off: make the legacy route tests authenticate (Day 10)."""

import pathlib

p = pathlib.Path("tests/test_api.py")
s = p.read_text(encoding="utf-8")

NAMES = [
    "test_classify_ticket_returns_routing_response",
    "test_ticket_context_returns_seeded_ticket",
    "test_ticket_context_returns_404_for_unknown_ticket",
    "test_chat_endpoint_successful_response",
    "test_chat_endpoint_missing_or_invalid_message",
    "test_chat_endpoint_agent_failure",
    "test_customer_inquiry_creates_reviewable_ai_draft",
    "test_customer_inquiry_agent_failure_creates_reviewable_handoff_draft",
    "test_customer_inquiry_without_ticket_id_creates_new_ticket",
    "test_customer_inquiry_repair_request_creates_job_and_assigns_engineer",
    "test_create_job_for_ticket_api_endpoint",
]

for name in NAMES:
    idx = s.index("def " + name + "(")
    end = s.index(") -> None:", idx)
    s = s[:end] + ", legacy_client, auth_headers" + s[end:]

s = s.replace("with TestClient(app) as client:", "with legacy_client as client:")

REPLACEMENTS = [
    (
        '                "customer_id": "customer-1",\n            },\n        )',
        '                "customer_id": "customer-1",\n            },\n            headers=auth_headers,\n        )',
    ),
    (
        'client.get("/api/v1/tickets/ticket-1/context")',
        'client.get(\n            "/api/v1/tickets/ticket-1/context", headers=auth_headers\n        )',
    ),
    (
        'client.get("/api/v1/tickets/does-not-exist/context")',
        'client.get(\n            "/api/v1/tickets/does-not-exist/context", headers=auth_headers\n        )',
    ),
    (
        '            json={"message": "What is the warranty policy for AC repairs?"},\n        )',
        '            json={"message": "What is the warranty policy for AC repairs?"},\n            headers=auth_headers,\n        )',
    ),
    (
        'client.post("/chat", json={})',
        'client.post("/chat", json={}, headers=auth_headers)',
    ),
    (
        'client.post("/chat", json={"message": ""})',
        'client.post(\n            "/chat", json={"message": ""}, headers=auth_headers\n        )',
    ),
    (
        'client.post("/chat", json={"message": "   "})',
        'client.post(\n            "/chat", json={"message": "   "}, headers=auth_headers\n        )',
    ),
    (
        '            json={"message": "Help with my boiler!"},\n        )',
        '            json={"message": "Help with my boiler!"},\n            headers=auth_headers,\n        )',
    ),
    (
        '                "message": "Hi, can you help me understand your opening hours?",\n            },\n        )',
        '                "message": "Hi, can you help me understand your opening hours?",\n            },\n            headers=auth_headers,\n        )',
    ),
    (
        '                "message": "can u tell me your business hours",\n            },\n        )',
        '                "message": "can u tell me your business hours",\n            },\n            headers=auth_headers,\n        )',
    ),
    (
        '                "message": "I need help with my new subscription",\n            },\n        )',
        '                "message": "I need help with my new subscription",\n            },\n            headers=auth_headers,\n        )',
    ),
    (
        "                ),\n            },\n        )\n\n        assert response.status_code == 201\n        body = response.json()\n        # Job creation is deferred until send",
        "                ),\n            },\n            headers=auth_headers,\n        )\n\n        assert response.status_code == 201\n        body = response.json()\n        # Job creation is deferred until send",
    ),
    (
        '                "service_area": "London",\n                "priority": "high",\n            },\n        )',
        '                "service_area": "London",\n                "priority": "high",\n            },\n            headers=auth_headers,\n        )',
    ),
]

for old, new in REPLACEMENTS:
    if old not in s:
        print("MISS:", old.splitlines()[0][:70])
    s = s.replace(old, new, 1)

p.write_text(s, encoding="utf-8")
print("rewritten")
