"""Unified exception hierarchy for the speedster package."""

from __future__ import annotations


class ValidationError(Exception):
    """Raised when agent output fails validation."""


class BreakdownValidationError(ValidationError):
    """Raised when a breakdown fails schema, structural, or graph checks."""
