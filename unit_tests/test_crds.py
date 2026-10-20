"""CRD storage schemas and their version markers."""

from __future__ import annotations

import pytest

from podiumd_tests.crds import Marker
from podiumd_tests.crds import has_field
from podiumd_tests.crds import is_established
from podiumd_tests.crds import storage_schema
from podiumd_tests.crds import wrong_markers


def _obj(**properties):
    return {"type": "object", "properties": properties}


IDP = _obj(alias={"type": "string"}, organizationLinks={"type": "array"})
SCHEMA = _obj(spec=_obj(realm=_obj(identityProviders={"type": "array", "items": IDP}), replicas={"type": "integer"}))


def _crd(name, schema, *, storage="v2beta1"):
    versions = [
        {"name": "v2alpha1", "storage": storage == "v2alpha1", "schema": {"openAPIV3Schema": _obj()}},
        {"name": "v2beta1", "storage": storage == "v2beta1", "schema": {"openAPIV3Schema": schema}},
    ]
    return {"metadata": {"name": name}, "spec": {"versions": versions}}


@pytest.mark.parametrize(
    ("path", "found"),
    [
        ("spec.replicas", True),
        ("spec.realm.identityProviders[].organizationLinks", True),
        ("spec.realm.identityProviders[].organizationId", False),
        ("spec.realm.identityProviders.organizationLinks", False),  # array without []
        ("spec.missing.deeper", False),
    ],
)
def test_has_field_walks_properties_and_array_items(path, found):
    assert has_field(SCHEMA, path) is found


def test_storage_schema_takes_the_storage_version():
    assert storage_schema(_crd("x", SCHEMA)) == SCHEMA
    assert storage_schema(_crd("x", SCHEMA, storage="v2alpha1")) == _obj()
    assert storage_schema({"spec": {}}) == {}


def test_is_established_needs_established_true():
    assert is_established({"status": {"conditions": [{"type": "Established", "status": "True"}]}})
    assert not is_established({"status": {"conditions": [{"type": "Established", "status": "False"}]}})
    assert not is_established({})


MARKERS = [
    Marker("imports", (26, 8, 0), "spec.realm.identityProviders[].organizationLinks"),
    Marker("imports", (26, 8, 0), "spec.realm.identityProviders[].organizationId", present=False),
    Marker("imports", (27, 0, 0), "spec.future"),
    Marker("keycloaks", (26, 8, 0), "spec.schedulingGroup"),
]


def test_wrong_markers_report_lacking_present_and_absent_crds():
    old_idp = _obj(alias={"type": "string"}, organizationId={"type": "string"})
    old = _obj(spec=_obj(realm=_obj(identityProviders={"type": "array", "items": old_idp})))
    assert wrong_markers([_crd("imports", old)], MARKERS, (26, 8, 1)) == [
        "imports: lacks spec.realm.identityProviders[].organizationLinks",
        "imports: has spec.realm.identityProviders[].organizationId",
        "keycloaks: not installed",
    ]


def test_wrong_markers_skip_markers_of_later_versions():
    assert wrong_markers([_crd("imports", SCHEMA)], MARKERS[:3], (26, 8, 1)) == []
    assert wrong_markers([_crd("imports", _obj())], MARKERS, (26, 7, 4)) == []
