"""Log groups and the job summary on a CI runner (GitHub Actions, Azure DevOps); nothing elsewhere (PLAN.md §7a)."""

from __future__ import annotations

import os

from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Generator
    from collections.abc import Mapping
    from pathlib import Path


def runner(environ: Mapping[str, str] | None = None) -> str | None:
    """ "github", "azure" or None, from the variables each runner sets."""
    environ = os.environ if environ is None else environ
    if environ.get("GITHUB_ACTIONS") == "true":
        return "github"
    if environ.get("TF_BUILD", "").lower() == "true":
        return "azure"
    return None


@contextmanager
def group(title: str, environ: Mapping[str, str] | None = None) -> Generator[None]:
    """Fold the block's output into a collapsible section of the job log."""
    marks = {"github": ("::group::", "::endgroup::"), "azure": ("##[group]", "##[endgroup]")}.get(runner(environ) or "")
    if marks:
        print(f"{marks[0]}{title}", flush=True)
    try:
        yield
    finally:
        if marks:
            print(marks[1], flush=True)


def publish_summary(summary: Path, environ: Mapping[str, str] | None = None) -> None:
    """Show the run's summary.md on the job's page: the step summary, or Azure DevOps' build summary."""
    environ = os.environ if environ is None else environ
    kind = runner(environ)
    if kind == "github" and environ.get("GITHUB_STEP_SUMMARY"):
        with open(environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as handle:  # noqa: PTH123  # a path string
            handle.write(summary.read_text(encoding="utf-8") + "\n")
    elif kind == "azure":
        print(f"##vso[task.uploadsummary]{summary.resolve()}", flush=True)
