"""ZAC's beheer of BPMN procesdefinities and their form.io forms, on a throwaway copy of podiumd-tests' process."""

from __future__ import annotations

import json
import uuid

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.bpmn import DEFINITIONS
from podiumd_tests.bootstrap.bpmn import PROCESS_KEY
from podiumd_tests.bootstrap.bpmn import deploy_process
from podiumd_tests.bootstrap.bpmn import deployed_files
from podiumd_tests.bootstrap.bpmn import process_files
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.responses import expect_status

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.component,
    pytest.mark.requires("zac", "openzaak", "pabc", "keycloak"),
    pytest.mark.source(
        "podiumd-tests",
        "ZAC team's regression scenarios before PodiumD 4.10 (docs/research/zac-scenario-gaps.md, bpmn): beheer of"
        " BPMN procesdefinities and form.io forms.",
    ),
]

# A form the process names in no user task.
UNUSED_FORM = "ptestUnusedForm"


def _definition(zac: requests.Session, zac_url: str, key: str) -> JsonObject | None:
    """ZAC's beheer view of the process's latest version, with its details; None when ZAC has none."""
    listed = entries(expect_status(zac.get(zac_url + DEFINITIONS, params={"details": "true"}), HTTPStatus.OK).json())
    return next((definition for definition in listed if definition.get("key") == key), None)


def _forms(definition: JsonObject, field: str) -> dict[str, object]:
    """The forms in the details' field (forms, orphanedForms) by name, each with whether it is uploaded."""
    return {
        str(form.get("formKey")): form.get("uploaded") for form in entries(section(definition, "details").get(field))
    }


@pytest.fixture(name="throwaway_process")
def fixture_throwaway_process(
    zac: requests.Session, urls: dict[str, str], registry: ResourceRegistry
) -> tuple[str, dict[str, str]]:
    """A key no process has, and podiumd-tests' process and forms under that key; cleanup deletes the process."""
    key = f"ptestBeheer{uuid.uuid4().hex[:8]}"
    files = process_files()
    model = files.pop(f"{PROCESS_KEY}.bpmn").replace(PROCESS_KEY, key)
    registry.add(f"BPMN process {key}", lambda: zac.delete(f"{urls['zac']}{DEFINITIONS}/{key}"))
    return key, {f"{key}.bpmn": model, **files}


@pytest.mark.scenario("""
    Given a BPMN procesdefinitie that no zaaktype uses
    When the beheerder uploads it without its forms
    Then ZAC lists it as version 1, not in use, with each form it needs not uploaded
    When the beheerder uploads its forms and a form it does not use
    Then ZAC lists each needed form as uploaded and the other as unused
    And the download is a ZIP named after its key and version, with the process, its forms and the unused form apart
    When the beheerder uploads the same procesdefinitie again
    Then ZAC still lists it as version 1
    When the beheerder uploads a changed procesdefinitie
    Then ZAC lists it as version 2
    When the beheerder deletes the unused form and the procesdefinitie
    Then ZAC lists the procesdefinitie no more
""")
def test_procesdefinitie_beheer_from_upload_to_delete(
    zac: requests.Session, urls: dict[str, str], throwaway_process: tuple[str, dict[str, str]]
) -> None:
    """Upload, versions, required and orphaned forms, ZIP download and delete of a process not in use."""
    zac_url = urls["zac"]
    key, files = throwaway_process
    model = {name: content for name, content in files.items() if name.endswith(".bpmn")}
    forms = {name: content for name, content in files.items() if name.endswith(".json")}
    deploy_process(zac, zac_url, key, model)
    first = _definition(zac, zac_url, key)
    assert first is not None
    assert (first.get("version"), section(first, "details").get("inUse")) == (1, False)
    names = {name.removesuffix(".json") for name in forms}
    assert _forms(first, "forms") == dict.fromkeys(names, False)

    unused = json.dumps({**json.loads(next(iter(forms.values()))), "name": UNUSED_FORM})
    deploy_process(zac, zac_url, key, {**forms, f"{UNUSED_FORM}.json": unused})
    uploaded = _definition(zac, zac_url, key)
    assert uploaded is not None
    assert (_forms(uploaded, "forms"), _forms(uploaded, "orphanedForms")) == (
        dict.fromkeys(names, True),
        {UNUSED_FORM: True},
    )
    download = zac.get(f"{zac_url}{DEFINITIONS}/{key}/download")
    assert f'filename="{key}-v1.zip"' in str(expect_status(download, HTTPStatus.OK).headers.get("Content-Disposition"))
    assert deployed_files(zac, zac_url, key) == {**model, **forms, f"unused-forms/{UNUSED_FORM}.json": unused}

    deploy_process(zac, zac_url, key, model)
    assert (_definition(zac, zac_url, key) or {}).get("version") == 1
    changed = {
        name: content.replace('name="podiumd-tests BPMN process"', 'name="podiumd-tests v2"')
        for name, content in model.items()
    }
    deploy_process(zac, zac_url, key, changed)
    assert (_definition(zac, zac_url, key) or {}).get("version") == 2

    deleted_form = zac.delete(f"{zac_url}{DEFINITIONS}/{key}/forms/{UNUSED_FORM}")
    expect_status(deleted_form, HTTPStatus.NO_CONTENT)
    expect_status(zac.delete(f"{zac_url}{DEFINITIONS}/{key}"), HTTPStatus.NO_CONTENT)
    assert _definition(zac, zac_url, key) is None


@pytest.mark.scenario("""
    Given the BPMN procesdefinitie of a zaaktype
    When the beheerder deletes it, or one of its forms
    Then ZAC refuses both: the procesdefinitie is in use
    And ZAC still lists it as in use
""")
def test_procesdefinitie_in_use_is_not_deleted(
    zac: requests.Session, urls: dict[str, str], need_bootstrap: Callable[..., None]
) -> None:
    """ZAC answers 400 to deleting a process a zaaktype-bpmn-configuration links, or a form its user tasks name."""
    need_bootstrap("zac-bpmn-process")
    zac_url = urls["zac"]
    form = next(name.removesuffix(".json") for name in sorted(process_files()) if name.endswith(".json"))
    expect_status(zac.delete(f"{zac_url}{DEFINITIONS}/{PROCESS_KEY}/forms/{form}"), HTTPStatus.BAD_REQUEST)
    expect_status(zac.delete(f"{zac_url}{DEFINITIONS}/{PROCESS_KEY}"), HTTPStatus.BAD_REQUEST)
    in_use = _definition(zac, zac_url, PROCESS_KEY)
    assert in_use is not None
    assert section(in_use, "details").get("inUse") is True
