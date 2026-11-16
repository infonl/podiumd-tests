"""The failure a known defect causes, apart from the test's other failures.

Every check error of the suite (UnexpectedStatusError, WaitTimeoutError) is an AssertionError, so an xfail with
raises=AssertionError also hides a broken setup; raises=DefectSymptomError hides only the checks in a `symptom()` block.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Generator


class DefectSymptomError(AssertionError):
    """A check in a symptom() block failed."""


@contextmanager
def symptom() -> Generator[None]:
    """Raise an AssertionError of the block as DefectSymptomError."""
    try:
        yield
    except DefectSymptomError:
        raise
    except AssertionError as error:
        raise DefectSymptomError(str(error)) from error
