"""Natural language date/time parsing for scheduling."""

from __future__ import annotations

import re
from datetime import datetime, timedelta

_DAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
    "mon": 0,
    "tue": 1,
    "tues": 1,
    "wed": 2,
    "thu": 3,
    "thur": 3,
    "thurs": 3,
    "fri": 4,
    "sat": 5,
    "sun": 6,
}

_TIME_PATTERNS = [
    (r"(\d{1,2})\s*am", lambda h: h if h != 12 else 0, 0),
    (r"(\d{1,2})\s*pm", lambda h: h + 12 if h != 12 else 12, 0),
    (r"(\d{1,2}):(\d{2})\s*am", lambda h: h if h != 12 else 0, 1),
    (r"(\d{1,2}):(\d{2})\s*pm", lambda h: h + 12 if h != 12 else 12, 1),
    (r"(\d{1,2}):(\d{2})", None, 1),
    (r"(\d{1,2})\s*o'clock", lambda h: h, 0),
]


def parse_natural_datetime(text: str) -> datetime | None:
    """Parse natural language date/time expressions like 'Monday at 9am'.

    Supported formats:
    - 'Monday at 9am', 'Monday 9:30pm'
    - 'next Monday at 9am'
    - 'this Friday at 5pm'
    - 'tomorrow at 9am'
    - 'today at 5pm'
    - '9am tomorrow'
    - ISO format: '2026-09-18T09:00:00'

    Returns a datetime object or None if parsing fails.
    """
    if not text or not text.strip():
        return None

    text = text.strip().lower()

    # Try ISO format first
    try:
        return datetime.fromisoformat(text)
    except (ValueError, TypeError):
        pass

    now = datetime.now()

    # Check for day name patterns
    day_match = re.search(
        r"(next\s+)?(\w+)\s+(?:at\s+)?(\d{1,2}(?::\d{2})?\s*[ap]m|\d{1,2}\s*o'clock|\d{1,2}(?::\d{2})?)",
        text,
    )
    if not day_match:
        # Try reversed order: time then day
        day_match = re.search(
            r"(\d{1,2}(?::\d{2})?\s*[ap]m|\d{1,2}\s*o'clock|\d{1,2}(?::\d{2})?)\s+(?:on\s+)?(next\s+)?(\w+)",
            text,
        )
        if day_match:
            time_str = day_match.group(1)
            next_prefix = day_match.group(2)
            day_name = day_match.group(3)
        else:
            return None
    else:
        next_prefix = day_match.group(1)
        day_name = day_match.group(2)
        time_str = day_match.group(3)

    # Parse the day
    day_num = _DAYS.get(day_name)
    if day_num is None:
        # Handle 'today' and 'tomorrow'
        if day_name == "today":
            target_date = now.date()
        elif day_name == "tomorrow":
            target_date = (now + timedelta(days=1)).date()
        else:
            return None
    else:
        # Calculate days until target day
        today_weekday = now.weekday()
        days_ahead = (day_num - today_weekday) % 7

        if days_ahead == 0 and next_prefix:
            days_ahead = 7
        else:
            target_date = (now + timedelta(days=days_ahead)).date()

        if day_name != "today" and day_name != "tomorrow":
            target_date = (
                now + timedelta(days=days_ahead if days_ahead > 0 else 7)
            ).date()

    # Parse the time
    hour, minute = _parse_time(time_str)
    if hour is None:
        return None

    # Combine date and time
    try:
        result = datetime(
            target_date.year, target_date.month, target_date.day, hour, minute
        )
        return result
    except ValueError:
        return None


def _parse_time(time_str: str) -> tuple[int | None, int]:
    """Parse time string like '9am', '9:30pm', '14:30' into (hour, minute)."""
    time_str = time_str.strip().lower()

    for pattern, hour_adjuster, has_minutes in _TIME_PATTERNS:
        match = re.match(pattern, time_str)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2)) if has_minutes and match.group(2) else 0

            if hour_adjuster:
                hour = hour_adjuster(hour)

            if 0 <= hour <= 23 and 0 <= minute <= 59:
                return hour, minute
            else:
                return None, 0

    # Try simple 24-hour format
    try:
        hour = int(time_str)
        if 0 <= hour <= 23:
            return hour, 0
    except ValueError:
        pass

    return None, 0


def format_schedule_datetime(dt: datetime) -> str:
    """Format a datetime for display to users."""
    days = [
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    ]
    day_name = days[dt.weekday()]

    hour = dt.hour
    minute = dt.minute
    ampm = "AM" if hour < 12 else "PM"
    display_hour = hour if hour <= 12 else hour - 12
    if display_hour == 0:
        display_hour = 12

    if minute > 0:
        return f"{day_name} at {display_hour}:{minute:02d} {ampm}"
    return f"{day_name} at {display_hour} {ampm}"
