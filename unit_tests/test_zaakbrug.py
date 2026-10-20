"""Unit tests for the ZaakBrug ZDS messages."""

from datetime import UTC
from datetime import datetime

from podiumd_tests.zaakbrug import ZKN
from podiumd_tests.zaakbrug import genereer_zaak_identificatie
from podiumd_tests.zaakbrug import zaak_identificatie


def test_zds_answer_gives_the_zaak_identificatie():
    answer = (
        f'<Envelope><Body><x:Du02 xmlns:x="{ZKN}"><x:zaak><x:identificatie>ZK2026-00001</x:identificatie>'
        "</x:zaak></x:Du02></Body></Envelope>"
    )
    assert zaak_identificatie(answer) == "ZK2026-00001"
    assert zaak_identificatie("<Envelope/>") is None
    envelope = genereer_zaak_identificatie(datetime(2026, 1, 2, 3, 4, 5, 670000, tzinfo=UTC))
    assert "<StUF:organisatie>1900</StUF:organisatie>" in envelope
    assert "<StUF:tijdstipBericht>2026010203040567</StUF:tijdstipBericht>" in envelope
