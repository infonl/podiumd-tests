"""KISS's Kibana answers its status API, not only a ready pod."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.kibana import kibana_status_level

if TYPE_CHECKING:
    from podiumd_tests.environment import Environment

pytestmark = [pytest.mark.component, pytest.mark.cluster, pytest.mark.requires("kiss", "cluster")]


@pytest.mark.source(
    "PI test_4_9_0_upgrade.py",
    "KISS Kibana is available: /api/status as user elastic answers status.overall.level available.",
)
def test_kibana_is_available(podiumd_env: Environment) -> None:
    """Kibana's /api/status, as user elastic, reports overall level available."""
    password = podiumd_env.credentials.optional("kiss_elastic_password")
    if password is None:
        pytest.skip("no secret kiss_elastic_password: add k8s_secret {name: kiss-es-elastic-user, key: elastic}")
    level = kibana_status_level(podiumd_env.kube, password)
    if level is None:
        pytest.skip("no Service kiss-kb-http: KISS runs without Kibana (eck-kibana.enabled false)")
    assert level == "available"
