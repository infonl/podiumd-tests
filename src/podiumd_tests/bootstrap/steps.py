"""The bootstrap steps, in the order they are applied (unbootstrap goes in reverse)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from podiumd_tests.bootstrap.openzaak import OpenZaakClient

if TYPE_CHECKING:
    from podiumd_tests.bootstrap import Step

STEPS: tuple[Step, ...] = (OpenZaakClient(),)
