"""Errors for tenant prompt resolution and Hub/fallback load."""

from __future__ import annotations


class MissingTenantPromptRefError(ValueError):
    """Tenant settings lack a non-empty prompt ref for the requested step key."""


class PromptUnavailableError(RuntimeError):
    """Hub pull failed and no git fallback exists for the hub id."""
