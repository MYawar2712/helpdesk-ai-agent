"""Deterministic intent classification for inbound customer messages.

No LLM call is made — this is a fast keyword/regex pre-classifier that runs
before the decision node so the LLM prompt is seeded with a strong prior.
"""

from __future__ import annotations

import re

from models import TicketIntent

_RULES: list[tuple[TicketIntent, re.Pattern[str]]] = [
    # Human escalation request — explicit ask for a human agent
    (
        TicketIntent.HUMAN_ESCALATION,
        re.compile(
            r"\b(speak to|talk to|transfer me to|connect me to|escalate to|"
            r"i want a human|talk to a person|speak to a person|"
            r"get me a (human|person|agent|representative))\b",
            re.IGNORECASE,
        ),
    ),
    # Cancel job
    (
        TicketIntent.CANCEL_JOB,
        re.compile(
            r"\b(cancel|cancellation|abort|drop (the |my )?(service|job|appointment|"
            r"visit|booking))\b",
            re.IGNORECASE,
        ),
    ),
    # Reschedule existing job
    (
        TicketIntent.RESCHEDULE_JOB,
        re.compile(
            r"\b(reschedule|postpone|move (my|the) (appointment|job|visit|booking)|"
            r"change (the |my )?(date|time|appointment|schedule))\b",
            re.IGNORECASE,
        ),
    ),
    # Modify existing job (not cancellation or reschedule)
    (
        TicketIntent.MODIFY_JOB,
        re.compile(
            r"\b("
            r"change my job|update my job|"
            r"modify (my |the )?(job|booking|appointment)|"
            r"job modification"
            r")\b",
            re.IGNORECASE,
        ),
    ),
    # Job status check
    (
        TicketIntent.JOB_STATUS,
        re.compile(
            r"\b(status of (my |the )?(job|booking|appointment|visit)|"
            r"where is my (engineer|technician)|"
            r"what('s| is) happening with my job|"
            r"update on (job|my job|my appointment)|"
            r"has (my|the) engineer (arrived|been sent)|"
            r"(job|booking) (status|update))\b",
            re.IGNORECASE,
        ),
    ),
    # Billing/invoice inquiry
    (
        TicketIntent.BILLING_INQUIRY,
        re.compile(
            r"\b(invoice|billing|payment|receipt|charge|charged|bill|"
            r"overdue|unpaid|refund|chargeback|overcharged|"
            r"how much (do i owe|is (my|the) bill)|"
            r"billing (question|query|issue|inquiry))\b",
            re.IGNORECASE,
        ),
    ),
    # Complaint
    (
        TicketIntent.COMPLAINT,
        re.compile(
            r"\b(complaint|complain|unhappy|dissatisfied|disappointed|"
            r"terrible (service|experience)|awful|unacceptable|"
            r"this is (not good|not acceptable|ridiculous)|"
            r"very (upset|angry|frustrated)|poor service)\b",
            re.IGNORECASE,
        ),
    ),
    # New service request — physical engineer visit required
    (
        TicketIntent.NEW_SERVICE_REQUEST,
        re.compile(
            r"\b(broken|not working|fix|repair|job lock|"
            r"(need|send|book|schedule|make|arrange|get|request|organize|"
            r"set up) (a |an )?"
            r"(engineer|technician|plumber|electrician|hvac|repair|inspection|visit|service|appointment|someone)|"
            r"(engineer|technician|plumber|electrician|hvac) (to visit|visit|needed)|"
            r"leaking|leak|burst (pipe|boiler|tank)|"
            r"no (hot water|heating|power|electricity)|"
            r"install(ation)?|maintenance (visit|call)|"
            r"air (conditioning|con) (broken|not working|faulty)|"
            r"boiler (broken|fault|not working|failed))\b",
            re.IGNORECASE,
        ),
    ),
    # Technical support / troubleshooting (software/config, not a site visit)
    (
        TicketIntent.TECHNICAL_SUPPORT,
        re.compile(
            r"\b(how do i (configure|set up|use|connect)|"
            r"error (code|message)|troubleshoot|"
            r"technical (help|support|issue|problem)|"
            r"how do I configure)\b",
            re.IGNORECASE,
        ),
    ),
]

# Fallback: everything else is a general inquiry
_FALLBACK = TicketIntent.GENERAL_INQUIRY


def classify_intent(text: str) -> TicketIntent:
    """Return the most likely TicketIntent for a customer message.

    Uses deterministic keyword/regex rules in priority order.
    Falls back to GENERAL_INQUIRY when no rule matches.
    """
    if not text or not text.strip():
        return _FALLBACK
    for intent, pattern in _RULES:
        if pattern.search(text):
            return intent
    return _FALLBACK
