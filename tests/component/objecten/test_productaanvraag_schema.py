"""The Productaanvraag-Dimpact objecttype holds Dimpact's published schema, so ZAC and Open Formulieren agree on it."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.names import PRODUCTAANVRAAG_OBJECTTYPE
from podiumd_tests.json_data import differences
from podiumd_tests.seed.objecten import dimpact_productaanvraag_schema
from podiumd_tests.seed.objecten import named_objecttypes
from podiumd_tests.seed.objecten import newest_version

if TYPE_CHECKING:
    from podiumd_tests.clients.api import ApiClient

pytestmark = [
    pytest.mark.component,
    pytest.mark.requires("objecttypen"),
    pytest.mark.source(
        "external Dimpact/objecttypes Productaanvraag/productaanvraag-dimpact.json",
        "Dimpact's canonical Productaanvraag-Dimpact schema for the Objecttypen API in PodiumD.",
    ),
]


@pytest.mark.scenario("""
    Given Dimpact's published Productaanvraag-Dimpact schema
    When the newest version of the Productaanvraag-Dimpact objecttype is read in Objecttypen
    Then its JSON schema equals Dimpact's
""")
def test_productaanvraag_schema_is_dimpacts(objecttypen: ApiClient) -> None:
    """The newest Productaanvraag-Dimpact version's jsonSchema equals Dimpact's published schema."""
    found = named_objecttypes(objecttypen, PRODUCTAANVRAAG_OBJECTTYPE)
    assert len(found) == 1, f"Objecttypen API lists {len(found)} objecttypes named {PRODUCTAANVRAAG_OBJECTTYPE}"
    deployed = newest_version(objecttypen, found[0]).get("jsonSchema")
    canonical = dimpact_productaanvraag_schema()
    drift = {"missing or changed": differences(canonical, deployed), "added": differences(deployed, canonical)}
    assert deployed == canonical, f"{PRODUCTAANVRAAG_OBJECTTYPE} schema differs from Dimpact's: {drift}"
