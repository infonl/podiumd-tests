"""A release leaves zaaktypen, ZAC's zaakafhandelparameters and existing zaken as they were.

Compares with the snapshot `podiumd-tests snapshot` recorded before the release.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from podiumd_tests import snapshot
from podiumd_tests.bootstrap.steps import ADMIN

if TYPE_CHECKING:
    from collections.abc import Callable

    from podiumd_tests.environment import Environment

pytestmark = [pytest.mark.integration, pytest.mark.requires("openzaak", "cluster")]


@pytest.mark.tc("ZAC-004", "FB-013", "FB-014")
def test_release_left_zaaktypen_and_zaken_unchanged(
    request: pytest.FixtureRequest, podiumd_env: Environment, need_bootstrap: Callable[..., None]
) -> None:
    """Every zaaktype, zaakafhandelparameters and sampled zaak of the snapshot is still there, unchanged."""
    junit = request.config.option.xmlpath
    if not junit:
        pytest.skip("no results directory: run through `podiumd-tests run`")
    name = podiumd_env.profile.name
    before = snapshot.latest(Path(junit).parents[2], name)
    if before is None:
        pytest.skip(f"no snapshot of {name}: run `podiumd-tests snapshot --env {name}` before a release")
    need_bootstrap("openzaak-client", ADMIN.name)
    after = snapshot.take(podiumd_env)
    if after["images"] == before["images"]:
        pytest.skip(f"Open Zaak and ZAC run the same images as at the snapshot of {before['taken']}")
    changed = snapshot.differences(before, after)
    assert not changed, f"since the snapshot of {before['taken']}:\n" + "\n".join(changed)
