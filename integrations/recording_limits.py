"""Shared exceptions for bounded physical recording ingestion."""

from __future__ import annotations


class RecordingSampleLimitExceeded(ValueError):
    """Raised before a loader retains more than its configured sample cap."""

    def __init__(self, rows: int, limit: int) -> None:
        self.rows = rows
        self.limit = limit
        super().__init__(
            f"Recording contains more than {limit} converted samples "
            f"(at least {rows}); the recording limit is {limit}."
        )
