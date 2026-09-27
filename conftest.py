"""Pytest bootstrap.

The test-suite runs against SQLite (``config.test_settings``) so it can be
executed without a running PostgreSQL / Redis / Celery stack. Celery tasks run
eagerly and e-mail is captured in-memory.
"""
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.test_settings")
os.environ.setdefault("DJANGO_SECRET_KEY", "test-secret-key")
os.environ.setdefault("CELERY_TASK_ALWAYS_EAGER", "1")
