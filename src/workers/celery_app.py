"""Celery application configuration for helpdesk background work."""

# ruff: noqa: E402

from __future__ import annotations

import os
import sys
from pathlib import Path

# Support both ``celery -A src.workers.celery_app`` and imports with ``src``
# already on PYTHONPATH. The project uses top-level imports within ``src``.
SRC_DIRECTORY = Path(__file__).resolve().parents[1]
if str(SRC_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SRC_DIRECTORY))

import fakeredis
from celery import Celery

USE_FAKE_REDIS = os.getenv("CELERY_USE_FAKE_REDIS", "0") == "1"
BROKER_URL = (
    "memory://"
    if USE_FAKE_REDIS
    else os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
)
RESULT_BACKEND = (
    "cache+memory://"
    if USE_FAKE_REDIS
    else os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")
)

_fake_redis = fakeredis.FakeRedis(decode_responses=True) if USE_FAKE_REDIS else None


def get_redis_client() -> fakeredis.FakeRedis | None:
    """Return the in-process fake Redis client when local mode is enabled."""

    return _fake_redis


celery_app = Celery("helpdesk", broker=BROKER_URL, backend=RESULT_BACKEND)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_routes={
        "workers.tasks.process_ticket_async": {"queue": "ticket_processing"},
        "workers.tasks.send_customer_notification_task": {"queue": "notifications"},
    },
)
celery_app.autodiscover_tasks(["workers"])
