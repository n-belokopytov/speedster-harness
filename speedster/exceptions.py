"""Unified exception hierarchy for the speedster package."""

from __future__ import annotations


class SpeedsterError(Exception):
    """Base exception for all speedster errors."""


class ValidationError(SpeedsterError):
    """Raised when agent output fails validation."""


class ContractValidationError(ValidationError):
    """Raised when a contract payload fails schema or structural checks."""


class BreakdownValidationError(ValidationError):
    """Raised when a breakdown fails schema, structural, or graph checks."""


class TaskNotFoundError(SpeedsterError):
    """Raised when a task cannot be found."""
