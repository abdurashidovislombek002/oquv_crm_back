"""Celery application for the CRM backend."""
from __future__ import annotations

import os

from celery import Celery
from celery.schedules import crontab  # noqa: F401  (used by dynamic schedules)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("crm")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


@app.task(bind=True, ignore_result=True)
def debug_task(self) -> str:  # pragma: no cover - diagnostic helper
    return f"Request: {self.request!r}"


@app.task(bind=True, ignore_result=True, name="crm.startup")
def startup_task(self) -> None:  # pragma: no cover - diagnostic helper
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
