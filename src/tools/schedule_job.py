"""LangChain tool for scheduling jobs at specific dates/times."""

from __future__ import annotations

from typing import Any

from langchain_core.tools import BaseTool

from utils.date_parser import parse_natural_datetime


class ScheduleJobTool(BaseTool):
    """Tool that extracts scheduling information and returns parsed datetime."""

    name: str = "schedule_job"
    description: str = """Use this tool when a customer wants to schedule a job
at a specific date/time.
Extract the scheduling information and return the parsed datetime in ISO format.
Examples:
- "Monday at 9am" -> extracts Monday 9:00 AM
- "Friday at 3:30pm" -> extracts Friday 3:30 PM
- "tomorrow at 10am" -> extracts tomorrow 10:00 AM
- "2026-09-18T09:00:00" -> extracts the exact datetime

The tool will return the parsed datetime in ISO format if successful,
or an error message if parsing fails."""

    def _run(self, scheduling_request: str = "", **kwargs: Any) -> dict[str, Any]:
        """Parse the request and return the datetime in ISO format."""
        text = (
            scheduling_request
            or kwargs.get("text")
            or kwargs.get("message")
            or kwargs.get("request")
            or ""
        )
        if not text and kwargs:
            for k, v in kwargs.items():
                if k not in {"customer_id", "ticket_id", "id"} and isinstance(v, str):
                    text = v
                    break
        parsed_dt = parse_natural_datetime(str(text))
        if parsed_dt is None:
            err_msg = (
                f"ERROR: Could not parse datetime from '{text}'. "
                "Use format like 'Monday at 9am' or ISO format '2026-09-18T09:00:00'."
            )
            return {"found": False, "error": err_msg, "result": err_msg}
        iso_str = parsed_dt.isoformat()
        return {"found": True, "scheduled_at": iso_str, "result": iso_str}

    async def _arun(
        self, scheduling_request: str = "", **kwargs: Any
    ) -> dict[str, Any]:
        """Async version - same implementation."""
        return self._run(scheduling_request, **kwargs)


def create_schedule_job_tool() -> ScheduleJobTool:
    """Create a schedule job tool instance."""
    return ScheduleJobTool()
