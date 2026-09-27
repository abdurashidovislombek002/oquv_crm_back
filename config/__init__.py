"""Root config package. Exposes the Celery app and triggers task autodiscovery."""
from .celery import app as celery_app

__all__ = ("celery_app",)
