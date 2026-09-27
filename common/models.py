"""Abstract base models shared by every app.

All concrete models inherit from :class:`BaseModel` which provides
``created_at`` / ``updated_at`` / ``is_active`` (soft delete) out of the box.
"""
from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

from common.querysets import ActiveQuerySet


class TimeStampedModel(models.Model):
    """Immutable creation date + auto-updated modification date."""

    created_at = models.DateTimeField(_("created at"), auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(_("updated at"), auto_now=True)

    class Meta:
        abstract = True


class BaseModel(TimeStampedModel):
    """Abstract base: timestamps + soft delete + handy querysets."""

    is_active = models.BooleanField(_("is active"), default=True, db_index=True)

    objects = models.Manager()
    active = ActiveQuerySet.as_manager()

    class Meta:
        abstract = True

    def soft_delete(self, save: bool = True) -> None:
        self.is_active = False
        if save:
            self.save(update_fields=["is_active", "updated_at"])

    def restore(self, save: bool = True) -> None:
        self.is_active = True
        if save:
            self.save(update_fields=["is_active", "updated_at"])

    def hard_delete(self) -> None:
        self.delete()


class BranchScopedModel(BaseModel):
    """Base for models that belong to a single branch (multi-tenant column)."""

    branch = models.ForeignKey(
        "branches.Branch",
        on_delete=models.CASCADE,
        related_name="%(class)ss",
        verbose_name=_("branch"),
    )

    class Meta:
        abstract = True
