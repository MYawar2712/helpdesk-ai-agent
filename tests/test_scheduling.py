"""Tests for scheduling functionality."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

import pytest

from services.operations import (
    BusinessRuleError,
    CustomerIdentity,
    HelpdeskOperationsService,
)
from utils.date_parser import format_schedule_datetime, parse_natural_datetime


@pytest.fixture()
def conn() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(
        """CREATE TABLE customers (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            phone TEXT NOT NULL,
            company TEXT NOT NULL,
            verification_status TEXT NOT NULL DEFAULT 'verified'
        )"""
    )
    connection.execute(
        """CREATE TABLE jobs (
            id TEXT PRIMARY KEY,
            customer_id TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            status TEXT NOT NULL,
            priority TEXT NOT NULL,
            assigned_engineer_id TEXT,
            service_area TEXT,
            required_skill TEXT,
            scheduled_at TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )"""
    )
    connection.execute(
        """CREATE TABLE audit_log (
            id TEXT PRIMARY KEY,
            actor_type TEXT NOT NULL,
            actor_id TEXT,
            action TEXT NOT NULL,
            resource_type TEXT NOT NULL,
            resource_id TEXT NOT NULL,
            customer_id TEXT,
            details TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )"""
    )
    return connection


@pytest.fixture()
def svc(conn) -> HelpdeskOperationsService:
    return HelpdeskOperationsService(conn)


@pytest.fixture()
def verified_customer(svc) -> CustomerIdentity:
    svc.connection.execute(
        """INSERT INTO customers (id, name, email, phone, company, verification_status)
        VALUES (?, ?, ?, ?, ?, ?)""",
        (
            "customer-1",
            "Alice",
            "alice@example.com",
            "123-456-7890",
            "ACME",
            "verified",
        ),
    )
    svc.connection.commit()
    return CustomerIdentity(customer_id="customer-1")


class TestParseNaturalDatetime:
    def test_monday_at_9am(self) -> None:
        # Next Monday is Sep 21
        result = parse_natural_datetime("Monday at 9am")
        # The result depends on current date, so we just check it's a datetime
        assert isinstance(result, datetime)
        assert result.hour == 9
        assert result.minute == 0

    def test_iso_format(self) -> None:
        result = parse_natural_datetime("2026-09-18T09:00:00")
        assert result == datetime(2026, 9, 18, 9, 0, 0)

    def test_tomorrow_at_10am(self) -> None:
        result = parse_natural_datetime("tomorrow at 10am")
        assert isinstance(result, datetime)
        assert result.hour == 10
        assert result > datetime.now()

    def test_invalid_text(self) -> None:
        assert parse_natural_datetime("") is None
        assert parse_natural_datetime("not a date") is None

    def test_future_date_only(self) -> None:
        result = parse_natural_datetime("Monday at 9am")
        assert result is None or result > datetime.now()


class TestValidateScheduledAt:
    def test_valid_iso_format(self, svc, verified_customer) -> None:
        future = datetime.now() + timedelta(days=1)
        svc._validate_scheduled_at(future.isoformat())

    def test_invalid_format(self, svc, verified_customer) -> None:
        with pytest.raises(BusinessRuleError, match="invalid datetime format"):
            svc._validate_scheduled_at("not-a-date")

    def test_past_date(self, svc, verified_customer) -> None:
        past = datetime.now() - timedelta(days=1)
        with pytest.raises(BusinessRuleError, match="must be a future date"):
            svc._validate_scheduled_at(past.isoformat())


class TestCreateJobWithSchedule:
    def test_create_job_with_scheduled_at(self, svc, verified_customer) -> None:
        future = datetime.now() + timedelta(days=1)
        job = svc.create_job(
            verified_customer,
            title="AC Repair",
            description="Fix AC unit",
            required_skill="HVAC",
            service_area="London",
            scheduled_at=future.isoformat(),
        )
        assert job["scheduled_at"] == future.isoformat()
        assert job["status"] == "pending"

    def test_create_job_without_schedule(self, svc, verified_customer) -> None:
        job = svc.create_job(
            verified_customer,
            title="AC Repair",
            description="Fix AC unit",
            required_skill="HVAC",
            service_area="London",
        )
        assert job["scheduled_at"] is None

    def test_create_job_with_invalid_schedule(self, svc, verified_customer) -> None:
        with pytest.raises(BusinessRuleError, match="invalid datetime format"):
            svc.create_job(
                verified_customer,
                title="AC Repair",
                description="Fix AC unit",
                required_skill="HVAC",
                service_area="London",
                scheduled_at="not-a-date",
            )

    def test_create_job_with_past_schedule(self, svc, verified_customer) -> None:
        past = datetime.now() - timedelta(hours=1)
        with pytest.raises(BusinessRuleError, match="must be a future date"):
            svc.create_job(
                verified_customer,
                title="AC Repair",
                description="Fix AC unit",
                required_skill="HVAC",
                service_area="London",
                scheduled_at=past.isoformat(),
            )


class TestFormatScheduleDatetime:
    def test_monday_morning(self) -> None:
        dt = datetime(2026, 9, 21, 9, 0)  # Monday
        result = format_schedule_datetime(dt)
        assert "Monday" in result
        assert "9" in result
        assert "AM" in result

    def test_friday_afternoon(self) -> None:
        dt = datetime(2026, 9, 18, 15, 30)  # Friday
        result = format_schedule_datetime(dt)
        assert "Friday" in result
        assert "3:30" in result
        assert "PM" in result
