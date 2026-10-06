"""Cleanup of created resources (PLAN.md §4B).

Factories register a deleter for everything they create. On teardown the
registry deletes in reverse order (LIFO), also when the test failed, and
reports every deleter that failed instead of stopping at the first one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass(frozen=True)
class _Entry:
    description: str
    delete: Callable[[], object]


class CleanupError(Exception):
    """One or more deleters failed; the message lists them all."""


class ResourceRegistry:
    """Created resources of one test, with their deleters."""

    def __init__(self, run_tag: str, *, keep: bool = False) -> None:
        self.run_tag = run_tag
        self.keep = keep
        self._entries: list[_Entry] = []

    def tagged(self, name: str) -> str:
        """A name carrying the run tag, so sweep can find leftovers (PLAN.md R9, R15)."""
        return f"{self.run_tag}-{name}"

    def add(self, description: str, delete: Callable[[], object]) -> None:
        """Register a deleter for a created resource."""
        self._entries.append(_Entry(description, delete))

    def __len__(self) -> int:
        return len(self._entries)

    def cleanup(self) -> list[str]:
        """Delete everything; return the descriptions kept (with keep=True) or raise CleanupError."""
        entries, self._entries = self._entries, []
        if self.keep:
            return [e.description for e in entries]
        errors: list[str] = []
        for entry in reversed(entries):
            try:
                entry.delete()
            except Exception as exc:  # noqa: BLE001  # pylint: disable=broad-exception-caught  # collect all, report together
                errors.append(f"{entry.description}: {type(exc).__name__}: {exc}")
        if errors:
            raise CleanupError("cleanup failed for: " + "; ".join(errors))
        return []
