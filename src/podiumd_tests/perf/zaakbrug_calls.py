"""The perf tier's ZaakBrug call: genereerZaakIdentificatie under concurrent load (ZaakBrug #714)."""

from __future__ import annotations

from datetime import UTC
from datetime import datetime
from typing import TYPE_CHECKING

from podiumd_tests.responses import expect_status
from podiumd_tests.zaakbrug import ZDS
from podiumd_tests.zaakbrug import genereer_zaak_id
from podiumd_tests.zaakbrug import is_fault
from podiumd_tests.zaakbrug import soap_action
from podiumd_tests.zaakbrug import zaak_identificatie

if TYPE_CHECKING:
    from podiumd_tests.environment import Environment
    from podiumd_tests.perf.zgw_calls import Call


def new_identificatie(answer: str, seen: set[str]) -> str:
    """Return the zaak identificatie of a genereerZaakIdentificatie answer and add it to seen.

    ValueError on a fault (Fo03), on no identificatie, or on one already in seen.
    """
    if is_fault(answer):
        msg = f"genereerZaakIdentificatie answered a fault: {' '.join(answer.split())[:300]}"
        raise ValueError(msg)
    identificatie = zaak_identificatie(answer)
    if not identificatie:
        msg = "genereerZaakIdentificatie answered no zaak identificatie"
        raise ValueError(msg)
    if identificatie in seen:
        msg = f"ZaakBrug handed out zaak identificatie {identificatie} twice"
        raise ValueError(msg)
    seen.add(identificatie)
    return identificatie


def zaakbrug_calls(env: Environment, seen: set[str]) -> dict[str, Call]:
    """Return ZaakBrug's genereerZaakIdentificatie, which fails on an identificatie in seen, the run's identificaties.

    With seen empty, it is called once first: parallel first calls break ZaakBrug's counter before 1.26.20
    (zaakbrug-2), and Locust creates its users one after another.
    """
    http = env.session(cookies=False)
    url = f"{env.profile.urls['zaakbrug']}{ZDS}/VrijBericht"
    headers = soap_action("genereerZaakIdentificatie_Di02")

    def genereer() -> str:
        envelope = genereer_zaak_id(datetime.now(UTC))
        return new_identificatie(expect_status(http.post(url, data=envelope, headers=headers), 200).text, seen)

    if not seen:
        genereer()
    return {"zaakbrug_genereer": lambda _registry: genereer()}
