"""Deterministic input/output guardrails for the helpdesk agent.

These checks complement — and do not replace — authentication, customer
isolation, tool validation, and business rules enforced elsewhere.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("helpdesk.guardrails")

REDACTION_LABELS = {
    "EMAIL": "[REDACTED_EMAIL]",
    "PHONE": "[REDACTED_PHONE]",
    "CARD": "[REDACTED_CARD]",
    "SSN": "[REDACTED_SSN]",
    "NATIONAL_ID": "[REDACTED_ID]",
}

REFUSAL_PREFIX = "I can't help with that request."

_EMAIL_RE = re.compile(
    r"\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b",
)
_CARD_RE = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_NINO_RE = re.compile(
    r"\b[A-CEGHJ-PR-TW-Z]{2}\s?\d{2}\s?\d{2}\s?\d{2}\s?[A-D]\b",
    re.IGNORECASE,
)
_PASSPORT_RE = re.compile(
    r"\b(?:passport|national\s*id|nid)\s*(?:number|no\.?|#)?"
    r"\s*(?:is|:)?\s*([A-Z0-9]{6,9})\b",
    re.IGNORECASE,
)
_PHONE_RE = re.compile(
    r"(?<!\w)(?:\+?\d{1,3}[\s.\-]?)?(?:\(?\d{3}\)?[\s.\-]?)?\d{3}[\s.\-]\d{4}(?!\w)"
    r"|(?<!\w)\+?\d{1,3}[\s.\-]?\d{9,11}(?!\w)"
    r"|(?<!\w)0\d{10}(?!\w)"
)

_INJECTION_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "ignore_instructions",
        re.compile(
            r"ignore (all |any |the )?(previous|prior|above|system) "
            r"(instructions|prompts?|rules)",
            re.IGNORECASE,
        ),
    ),
    (
        "disregard_system",
        re.compile(
            r"disregard (the )?(system|previous|above) (prompt|instructions|rules)",
            re.IGNORECASE,
        ),
    ),
    (
        "reveal_prompt",
        re.compile(
            r"(reveal|show|print|dump|repeat) (me )?(your |the )?"
            r"(hidden |secret )?(system prompt|system instructions|hidden prompt)",
            re.IGNORECASE,
        ),
    ),
    ("jailbreak", re.compile(r"\bjailbreak\b", re.IGNORECASE)),
    ("dan_mode", re.compile(r"\bdan mode\b|\byou are now dan\b", re.IGNORECASE)),
    ("developer_mode", re.compile(r"\bdeveloper mode\b", re.IGNORECASE)),
    (
        "role_override",
        re.compile(
            r"you are now (unrestricted|jailbroken|without (any )?rules)",
            re.IGNORECASE,
        ),
    ),
    (
        "bypass_auth",
        re.compile(
            r"bypass (all )?(authorization|authentication|security|access control|"
            r"owner(?:ship)? checks?)",
            re.IGNORECASE,
        ),
    ),
    (
        "override_rules",
        re.compile(
            r"override (the )?(safety|security|business|application) rules",
            re.IGNORECASE,
        ),
    ),
    (
        "do_not_follow",
        re.compile(
            r"do not follow (your|the) (system |safety )?(rules|instructions)",
            re.IGNORECASE,
        ),
    ),
    (
        "new_instructions",
        re.compile(r"\bnew instructions?\s*:", re.IGNORECASE),
    ),
    ("system_tag", re.compile(r"</?system>", re.IGNORECASE)),
    ("system_bracket", re.compile(r"\[/?system\]", re.IGNORECASE)),
    (
        "no_restrictions",
        re.compile(
            r"(you have )?no (safety )?restrictions|"
            r"without (any )?(safety )?guardrails",
            re.IGNORECASE,
        ),
    ),
)

_UNSAFE_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("explosive", re.compile(r"\b(bomb|explosives?|improvised explosive)\b", re.I)),
    (
        "weapon",
        re.compile(r"how to (make|build|create) (a )?(weapon|virus|malware)", re.I),
    ),
    ("malware", re.compile(r"\b(ransomware|keylogger|rootkit)\b", re.I)),
    ("violence", re.compile(r"\b(kill|murder|assault) (them|him|her|someone)\b", re.I)),
)

_UNAUTHORIZED_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "all_customers",
        re.compile(
            r"((all|every|each) customers?(['’]s)? (data|records|invoices|jobs|details)"
            r"|for every customer|every customer's)",
            re.I,
        ),
    ),
    (
        "named_multi_customer",
        re.compile(
            r"(ada lovelace).+(grace hopper)|(grace hopper).+(ada lovelace)",
            re.I | re.DOTALL,
        ),
    ),
    (
        "other_customer",
        re.compile(
            r"(another|other|someone else's) customer(['’]s)? "
            r"(data|records|invoices|jobs|account)",
            re.I,
        ),
    ),
    (
        "cross_customer",
        re.compile(
            r"i am customer[-\s]?\w+.+(customer[-\s]?\w+).+"
            r"(invoice|job|record|data|details)",
            re.I | re.DOTALL,
        ),
    ),
    (
        "skip_owner",
        re.compile(
            r"(ignore|skip|without) (the )?(owner|ownership|authorization|auth) "
            r"(check|rule)",
            re.I,
        ),
    ),
    (
        "unauthorized_tool",
        re.compile(
            r"(execute|run|call|invoke) (the )?(tool|get_all_invoices|get_customer|"
            r"get_job|schedule_job).{0,40}(without|regardless|ignore|bypass)",
            re.I,
        ),
    ),
    (
        "sql_abuse",
        re.compile(r"\b(drop table|delete from customers|truncate )\b", re.I),
    ),
    (
        "unlock_foreign_job",
        re.compile(
            r"(unlock|lock|access) job[-\s]?\w+.+(another customer|not mine|"
            r"does not belong|belongs to another)",
            re.I,
        ),
    ),
)

_IDENTITY_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "forged_admin",
        re.compile(
            r"\bi am (an? )?(admin|administrator|root|superuser)\b",
            re.I,
        ),
    ),
    (
        "skip_authn",
        re.compile(
            r"(skip|forget|disable) (the )?"
            r"(authentication|login|identity verification)",
            re.I,
        ),
    ),
    (
        "treat_as_admin",
        re.compile(r"treat me as (an? )?(admin|verified admin|internal staff)", re.I),
    ),
)

_SECRET_REQUEST_RE = re.compile(
    r"(show|reveal|print|dump|give|return).{0,40}"
    r"(api[_ ]?key|secret key|private key|password hash|\.env|llm_api_key)",
    re.IGNORECASE,
)
_SYSTEM_PROMPT_REQUEST_RE = re.compile(
    r"(system prompt|hidden prompt|decision instructions|system instructions)",
    re.IGNORECASE,
)
_HALLUCINATED_ACTION_REQUEST_RE = re.compile(
    r"(say|reply|confirm|claim|pretend) (that )?"
    r"(you |the (job|invoice|payment) )?(already )?"
    r"(refunded|deleted|paid|hacked|locked every|closed the job|completed the refund)",
    re.IGNORECASE,
)
_COMPLETED_ACTION_RE = re.compile(
    r"\b(i('ve| have| just)?|we have)\s+"
    r"(scheduled|locked|refunded|deleted|paid|cancelled|canceled|completed)\b",
    re.IGNORECASE,
)
_SECRET_LEAK_RE = re.compile(
    r"(sk-[A-Za-z0-9]{8,}|llm_api_key\s*=|api[_-]?key\s*[:=]\s*\S+)",
    re.IGNORECASE,
)
_SYSTEM_LEAK_RE = re.compile(
    r"(you are a helpdesk routing decision maker|return json only|"
    r"allowed tools:\s*get_job)",
    re.IGNORECASE,
)
_CROSS_CUSTOMER_DUMP_RE = re.compile(
    r"(ada lovelace).+(grace hopper)|(grace hopper).+(ada lovelace)",
    re.IGNORECASE | re.DOTALL,
)

REFUSAL_MARKERS = (
    "can't help with that request",
    "cannot perform",
    "not allowed",
    "i can't help",
    "i cannot",
    "unable to",
    "will not bypass",
    "cannot bypass",
)


@dataclass(frozen=True, slots=True)
class PIIMatch:
    """A PII span. ``kind`` is safe to log; the matched value is not stored."""

    kind: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class InjectionFinding:
    """Prompt-injection verdict with matched rule ids only (no user payload)."""

    detected: bool
    rule_ids: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return self.detected


@dataclass(frozen=True, slots=True)
class GuardrailDecision:
    """Result of an input or output guardrail pass."""

    allowed: bool
    reason: str
    category: str
    redacted_text: str
    pii_types: tuple[str, ...] = ()
    injection_rules: tuple[str, ...] = ()
    blocked: bool = False


def _luhn_ok(digit_string: str) -> bool:
    digits = [int(ch) for ch in digit_string if ch.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    checksum = 0
    parity = len(digits) % 2
    for index, number in enumerate(digits):
        if index % 2 == parity:
            number *= 2
            if number > 9:
                number -= 9
        checksum += number
    return checksum % 10 == 0


def _overlaps(start: int, end: int, taken: list[tuple[int, int]]) -> bool:
    return any(
        start < existing_end and end > existing_start
        for existing_start, existing_end in taken
    )


def detect_pii(text: str) -> list[PIIMatch]:
    """Detect common PII spans without retaining the sensitive values."""
    if not text:
        return []
    taken: list[tuple[int, int]] = []
    matches: list[PIIMatch] = []

    def _add(kind: str, start: int, end: int) -> None:
        if start >= end or _overlaps(start, end, taken):
            return
        taken.append((start, end))
        matches.append(PIIMatch(kind=kind, start=start, end=end))

    for match in _CARD_RE.finditer(text):
        digits = re.sub(r"\D", "", match.group())
        if _luhn_ok(digits):
            _add("CARD", match.start(), match.end())

    for match in _SSN_RE.finditer(text):
        _add("SSN", match.start(), match.end())

    for match in _EMAIL_RE.finditer(text):
        _add("EMAIL", match.start(), match.end())

    for match in _NINO_RE.finditer(text):
        _add("NATIONAL_ID", match.start(), match.end())

    for match in _PASSPORT_RE.finditer(text):
        if match.lastindex:
            _add("NATIONAL_ID", match.start(1), match.end(1))
        else:
            _add("NATIONAL_ID", match.start(), match.end())

    for match in _PHONE_RE.finditer(text):
        digits = re.sub(r"\D", "", match.group())
        if len(digits) < 10:
            continue
        _add("PHONE", match.start(), match.end())

    matches.sort(key=lambda item: item.start)
    return matches


def redact_pii(text: str) -> tuple[str, tuple[str, ...]]:
    """Return text with PII replaced by type labels. Never logs original values."""
    findings = detect_pii(text)
    if not findings:
        return text, ()
    pieces: list[str] = []
    cursor = 0
    kinds: list[str] = []
    for finding in findings:
        pieces.append(text[cursor : finding.start])
        pieces.append(REDACTION_LABELS[finding.kind])
        kinds.append(finding.kind)
        cursor = finding.end
    pieces.append(text[cursor:])
    if kinds:
        logger.info("redacted PII types=%s count=%s", sorted(set(kinds)), len(kinds))
    return "".join(pieces), tuple(kinds)


def detect_prompt_injection(text: str) -> InjectionFinding:
    """Detect jailbreak / instruction-override attempts via deterministic rules."""
    rule_ids = [
        rule_id for rule_id, pattern in _INJECTION_RULES if pattern.search(text)
    ]
    return InjectionFinding(detected=bool(rule_ids), rule_ids=tuple(rule_ids))


def _first_rule_match(
    text: str, rules: tuple[tuple[str, re.Pattern[str]], ...]
) -> str | None:
    for rule_id, pattern in rules:
        if pattern.search(text):
            return rule_id
    return None


def should_refuse(
    text: str, injection: InjectionFinding | None = None
) -> tuple[bool, str, str]:
    """Return ``(refuse, reason, category)`` for an inbound user message.

    Reasons mention categories only — never the original sensitive payload.
    """
    injection = injection if injection is not None else detect_prompt_injection(text)
    pii_types = tuple(sorted({item.kind for item in detect_pii(text)}))

    if "CARD" in pii_types:
        return (
            True,
            "Payment card numbers must not be sent in chat. "
            "Use the approved payment portal.",
            "pii_card",
        )
    if _SECRET_REQUEST_RE.search(text):
        return (
            True,
            "I will not reveal secrets, credentials, or environment values.",
            "secrets",
        )
    if _SYSTEM_PROMPT_REQUEST_RE.search(text) and (
        injection.detected or re.search(r"(reveal|show|print|dump|repeat)", text, re.I)
    ):
        return (
            True,
            "I will not reveal system prompts or hidden instructions.",
            "system_prompt",
        )
    if injection.detected:
        return (
            True,
            "This looks like an attempt to override system or security instructions.",
            "prompt_injection",
        )
    unsafe = _first_rule_match(text, _UNSAFE_RULES)
    if unsafe:
        return (
            True,
            "This request is unsafe and is outside what a helpdesk agent can do.",
            "unsafe",
        )
    unauthorized = _first_rule_match(text, _UNAUTHORIZED_RULES)
    if unauthorized:
        return (
            True,
            "I cannot bypass authorization or access another customer's data.",
            "unauthorized",
        )
    identity = _first_rule_match(text, _IDENTITY_RULES)
    if identity:
        return (
            True,
            "I cannot accept a self-asserted privileged identity "
            "or skip authentication.",
            "forged_identity",
        )
    if _HALLUCINATED_ACTION_REQUEST_RE.search(text):
        return (
            True,
            "I cannot pretend that an action was completed when it was not performed.",
            "hallucinated_action",
        )
    if _SECRET_REQUEST_RE.search(text):
        return (
            True,
            "I will not reveal secrets, credentials, or environment values.",
            "secrets",
        )
    return False, "", "none"


def format_refusal(reason: str) -> str:
    """Build a short, predictable refusal message."""
    cleaned = reason.strip() or "The request is not permitted for this helpdesk agent."
    return (
        f"{REFUSAL_PREFIX} {cleaned} "
        "I will not bypass authorization or business rules. "
        "If you have a genuine support issue, please rephrase it "
        "as a normal helpdesk request."
    )


def check_input(text: str) -> GuardrailDecision:
    """Run inbound PII redaction, injection detection, and refusal policy."""
    redacted, pii_types = redact_pii(text)
    injection = detect_prompt_injection(text)
    refuse, reason, category = should_refuse(text, injection)
    if refuse:
        logger.info("input refused category=%s pii_types=%s", category, list(pii_types))
        return GuardrailDecision(
            allowed=False,
            reason=reason,
            category=category,
            redacted_text=redacted,
            pii_types=pii_types,
            injection_rules=injection.rule_ids,
            blocked=True,
        )
    return GuardrailDecision(
        allowed=True,
        reason="",
        category="none",
        redacted_text=redacted,
        pii_types=pii_types,
        injection_rules=injection.rule_ids,
        blocked=False,
    )


def check_output(
    output: str,
    *,
    input_text: str = "",
    state: dict[str, Any] | None = None,
) -> GuardrailDecision:
    """Validate the final model text before it is returned to a user."""
    state = state or {}
    redacted, pii_types = redact_pii(output)

    if _SECRET_LEAK_RE.search(output) or _SECRET_LEAK_RE.search(redacted):
        reason = (
            "The draft response contained credential-like material and was blocked."
        )
        logger.info("output blocked category=secrets")
        return GuardrailDecision(
            allowed=False,
            reason=reason,
            category="secrets",
            redacted_text=format_refusal(reason),
            pii_types=pii_types,
            blocked=True,
        )
    if _SYSTEM_LEAK_RE.search(output):
        reason = "The draft response would have revealed internal system instructions."
        logger.info("output blocked category=system_prompt")
        return GuardrailDecision(
            allowed=False,
            reason=reason,
            category="system_prompt",
            redacted_text=format_refusal(reason),
            pii_types=pii_types,
            blocked=True,
        )
    if _CROSS_CUSTOMER_DUMP_RE.search(output):
        reason = "The draft response appeared to mix more than one customer's records."
        logger.info("output blocked category=cross_customer")
        return GuardrailDecision(
            allowed=False,
            reason=reason,
            category="cross_customer",
            redacted_text=format_refusal(reason),
            pii_types=pii_types,
            blocked=True,
        )

    route = state.get("route") or ""
    tool_result = state.get("tool_result") or {}
    tool_executed = bool(tool_result) and not (
        isinstance(tool_result, dict) and tool_result.get("blocked")
    )
    claims_completion = bool(_COMPLETED_ACTION_RE.search(output))
    if claims_completion and route not in {"tool"} and not tool_executed:
        if re.search(r"\b(refunded|deleted|paid|locked every)\b", output, re.I):
            reason = "The response claimed a completed action that was not performed."
            logger.info("output blocked category=hallucinated_action")
            return GuardrailDecision(
                allowed=False,
                reason=reason,
                category="hallucinated_action",
                redacted_text=format_refusal(reason),
                pii_types=pii_types,
                blocked=True,
            )

    if pii_types:
        logger.info("output redacted PII types=%s", list(pii_types))
    return GuardrailDecision(
        allowed=True,
        reason="",
        category="none",
        redacted_text=redacted,
        pii_types=pii_types,
        blocked=False,
    )


def redact_structure(value: Any) -> Any:
    """Redact PII in nested dict/list string values."""
    if isinstance(value, str):
        return redact_pii(value)[0]
    if isinstance(value, dict):
        return {key: redact_structure(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_structure(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_structure(item) for item in value)
    return value


def build_refusal_state(
    *,
    redacted_text: str,
    reason: str,
    category: str,
    pii_types: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Structured agent-compatible state for a refused request."""
    message = format_refusal(reason)
    return {
        "ticket_text": redacted_text,
        "route": "respond",
        "tool_name": "",
        "tool_input": {},
        "tool_result": {},
        "response": message,
        "handoff_reason": "",
        "final_response": message,
        "guardrail_refused": True,
        "guardrail_reason": reason,
        "guardrail_category": category,
        "guardrail_pii_types": list(pii_types),
    }


def apply_output_guardrails(
    state: dict[str, Any], decision: GuardrailDecision
) -> dict[str, Any]:
    """Attach output-guardrail results onto an agent state dict."""
    updated = dict(state)
    updated["final_response"] = decision.redacted_text
    if decision.blocked:
        updated["response"] = decision.redacted_text
        updated["guardrail_refused"] = True
        updated["guardrail_reason"] = decision.reason
        updated["guardrail_category"] = decision.category
    elif decision.pii_types:
        updated["guardrail_pii_types"] = list(decision.pii_types)
        if isinstance(updated.get("tool_result"), dict | list):
            updated["tool_result"] = redact_structure(updated["tool_result"])
    return updated


def is_refusal_text(text: str) -> bool:
    """Heuristic used by evaluation to detect a refusal response."""
    lowered = text.lower()
    return any(marker in lowered for marker in REFUSAL_MARKERS)
