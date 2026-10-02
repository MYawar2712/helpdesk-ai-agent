"""Deterministic response templates to replace LLM-based response generation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ResponseContext:
    """Minimal context needed for template rendering."""

    ticket_text: str = ""
    tool_result: dict[str, Any] | None = None
    intent: str = ""
    job_id: str | None = None
    invoice_id: str | None = None
    customer_id: str | None = None
    handoff_reason: str = ""


class ResponseTemplates:
    """Generate deterministic responses without LLM calls."""

    @staticmethod
    def tool_result_response(ctx: ResponseContext) -> str:
        """Format tool results into customer-friendly responses."""
        if not ctx.tool_result:
            return "I couldn't retrieve that information. Please try again."

        result = ctx.tool_result

        # Job lookup
        if "job" in result and result.get("found"):
            job = result["job"]
            status = job.get("status", "unknown").replace("_", " ").title()
            title = job.get("title", "the job")
            scheduled = job.get("scheduled_at")
            if scheduled:
                return (
                    f"Job **{job['id']}** ({title}) is **{status}** and scheduled "
                    f"for {scheduled}."
                )
            return f"Job **{job['id']}** ({title}) is **{status}**."

        # Job not found
        if "job" in result and not result.get("found"):
            error = result.get("error", "not found")
            if "Unauthorized" in error or "Privacy" in error:
                return (
                    "For privacy and security reasons, I cannot provide job details "
                    "belonging to another customer."
                )
            return f"I couldn't find that job. {error}"

        # Customer jobs list
        if "customer" in result and result.get("found"):
            customer = result["customer"]
            jobs = customer.get("jobs", [])
            if not jobs:
                return "You don't have any scheduled jobs."
            lines = [f"You have **{len(jobs)}** job(s):"]
            for j in jobs[:5]:
                status = j.get("status", "unknown").replace("_", " ").title()
                title = j.get("title", "Service visit")
                scheduled = j.get("scheduled_at", "TBD")
                lines.append(f"- **{j['id']}**: {title} — {status} ({scheduled})")
            if len(jobs) > 5:
                lines.append(f"... and {len(jobs) - 5} more.")
            return "\n".join(lines)

        # Invoice lookup
        if "invoice" in result and result.get("found"):
            inv = result["invoice"]
            amount = inv.get("amount", 0)
            status = inv.get("status", "unknown").title()
            due = inv.get("due_date", "N/A")
            return (
                f"Invoice **{inv['id']}**: **${amount:.2f}**, status **{status}**, "
                f"due {due}."
            )

        # Customer invoices list
        if "invoices" in result:
            invoices = result.get("invoices", [])
            if not invoices:
                return "You don't have any matching invoices."
            total = sum(inv.get("amount", 0) for inv in invoices)
            lines = [f"Found **{len(invoices)}** invoice(s) (total: **${total:.2f}**):"]
            for inv in invoices[:5]:
                status = inv.get("status", "unknown").title()
                due = inv.get("due_date", "N/A")
                amt = inv.get("amount", 0)
                lines.append(f"- **{inv['id']}**: ${amt:.2f} — {status} (due {due})")
            if len(invoices) > 5:
                lines.append(f"... and {len(invoices) - 5} more.")
            return "\n".join(lines)

        # Job cancellation
        if ctx.tool_result.get("tool") == "cancel_job" and ctx.tool_result.get("ok"):
            return f"Job **{ctx.job_id}** has been cancelled."

        # Job reschedule/update
        if ctx.tool_result.get("tool") in (
            "update_job_status",
            "reschedule_job",
        ) and ctx.tool_result.get("ok"):
            return f"Job **{ctx.job_id}** has been updated."

        # Job creation
        if ctx.tool_result.get("tool") == "create_job" and ctx.tool_result.get("ok"):
            job = ctx.tool_result.get("job", {})
            jid = job.get("id", ctx.job_id or "new job")
            return f"Your service visit has been scheduled. Job ID: **{jid}**."

        # Generic tool result
        if result.get("ok"):
            msg = result.get("message", "Action completed successfully.")
            return msg

        error = result.get("error", "An error occurred.")
        if "requires_job_id" in error or "job_id" in error:
            return "Please provide the specific job ID you'd like me to work with."
        return f"I couldn't complete that action: {error}"

    @staticmethod
    def handoff_response(ctx: ResponseContext) -> str:
        """Generate handoff message."""
        reason = ctx.handoff_reason or "Your request requires human support."
        return f"I'm handing this to a human support specialist. Reason: {reason}"

    @staticmethod
    def new_service_request_response() -> str:
        return (
            "Your service visit request has been received and is awaiting support "
            "approval. "
            "The job will be created after approval, and the confirmation will "
            "include your job ID."
        )

    @staticmethod
    def general_fallback() -> str:
        return (
            "I'm not sure I understand. Could you please provide more details about "
            "what you need help with?"
        )

    @staticmethod
    def rag_fallback() -> str:
        return (
            "I'm sorry, but I don't have enough information in the knowledge base "
            "to answer "
            "your question accurately. Please contact human support for assistance."
        )

    @staticmethod
    def error_response() -> str:
        return (
            "I'm sorry, I couldn't process your request. Please try again or ask "
            "for a human agent."
        )

    @classmethod
    def route_response(cls, route: str, ctx: ResponseContext) -> str:
        """Dispatch to the appropriate template based on route."""
        if route == "tool":
            return cls.tool_result_response(ctx)
        elif route == "handoff":
            return cls.handoff_response(ctx)
        elif route == "respond":
            if ctx.intent == "NEW_SERVICE_REQUEST":
                return cls.new_service_request_response()
            return cls.general_fallback()
        elif route == "rag":
            return cls.rag_fallback()
        return cls.error_response()


def format_tool_response(route: str, state: dict[str, Any]) -> str:
    """Convenience function to format response from graph state."""
    ctx = ResponseContext(
        ticket_text=state.get("ticket_text", ""),
        tool_result=state.get("tool_result"),
        intent=state.get("intent", ""),
        job_id=state.get("job_id"),
        invoice_id=state.get("invoice_id"),
        customer_id=state.get("customer_id"),
        handoff_reason=state.get("handoff_reason", ""),
    )
    return ResponseTemplates.route_response(route, ctx)
