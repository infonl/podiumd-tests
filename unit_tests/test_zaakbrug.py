"""Unit tests for the ZaakBrug ZDS messages."""

import xml.etree.ElementTree as ET  # nosec B405  # parses an envelope built here

from dataclasses import replace
from datetime import UTC
from datetime import datetime

from podiumd_tests.zaakbrug import ZKN
from podiumd_tests.zaakbrug import ZaakVelden
from podiumd_tests.zaakbrug import actualiseer_zaakstatus
from podiumd_tests.zaakbrug import cancel_checkout
from podiumd_tests.zaakbrug import checked_out_id
from podiumd_tests.zaakbrug import creeer_zaak
from podiumd_tests.zaakbrug import geef_zaakdocument_bewerken
from podiumd_tests.zaakbrug import genereer_zaak_identificatie
from podiumd_tests.zaakbrug import is_bevestiging
from podiumd_tests.zaakbrug import is_fault
from podiumd_tests.zaakbrug import update_zaak
from podiumd_tests.zaakbrug import update_zaakdocument
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


def test_creeer_zaak_envelope_has_short_code_and_initiator():
    envelope = creeer_zaak(datetime(2026, 1, 2, 3, 4, 5, 670000, tzinfo=UTC), "ZK2026-1", "ZBTESTPT", "111111110")
    assert "<ZKN:code>ZBTESTPT</ZKN:code>" in envelope
    assert "<BG:inp.bsn>111111110</BG:inp.bsn>" in envelope
    assert "<StUF:tijdstipBericht>2026010203040567</StUF:tijdstipBericht>" in envelope


def test_is_bevestiging():
    assert is_bevestiging('<E xmlns:S="http://www.egem.nl/StUF/StUF0301"><S:berichtcode>Bv03</S:berichtcode></E>')
    assert not is_bevestiging('<E xmlns:S="http://www.egem.nl/StUF/StUF0301"><S:berichtcode>Fo03</S:berichtcode></E>')


def test_update_zaak_carries_the_old_and_the_new_zaak_in_stuf_order():
    old = ZaakVelden(kenmerk="K-1", verlenging=(5, "Eerste"))
    envelope = update_zaak(
        datetime(2026, 10, 21, tzinfo=UTC), "Z-1", "ZT", old=old, new=replace(old, verlenging=(10, "Nieuw"))
    )
    objects = ET.fromstring(envelope).findall(f".//{{{ZKN}}}object")  # noqa: S314  # nosec B314  # built here
    assert [o.findtext(f"{{{ZKN}}}verlenging/{{{ZKN}}}duur") for o in objects] == ["5", "10"]
    tags = [child.tag.split("}")[1] for child in objects[0]]
    assert tags.index("kenmerk") < tags.index("startdatum") < tags.index("verlenging") < tags.index("isVan")
    assert ZaakVelden().kenmerk_xml() == ZaakVelden().verlenging_xml() == ""


def test_status_and_document_envelopes():
    now = datetime(2026, 10, 21, 13, 0, 5, tzinfo=UTC)
    status = actualiseer_zaakstatus(now, "Z-1", "ZT", volgnummer=2, omschrijving="In behandeling", gezet=now)
    assert "<ZKN:volgnummer>0002</ZKN:volgnummer>" in status
    assert "<ZKN:datumStatusGezet>2026102113000500</ZKN:datumStatusGezet>" in status
    assert 'xsi:nil="true" StUF:noValue="geenWaarde"/></ZKN:object>' in status  # the old zaak had no status
    assert "<ZKN:checkedOutId>C-1</ZKN:checkedOutId>" in update_zaakdocument(now, "Z-1", "D-1", "C-1", titel="nieuw")
    assert "geefZaakdocumentbewerken_Di02" in geef_zaakdocument_bewerken(now, "D-1")
    assert "<ZKN:identificatie>D-1</ZKN:identificatie>" in cancel_checkout(now, "D-1", "C-1")


def test_checked_out_id_and_fault():
    answer = f'<Envelope><Body><x:Du02 xmlns:x="{ZKN}"><x:checkedOutId>C-9</x:checkedOutId></x:Du02></Body></Envelope>'
    assert checked_out_id(answer) == "C-9"
    assert checked_out_id("<Envelope/>") is None
    fault = '<e:Envelope xmlns:e="http://schemas.xmlsoap.org/soap/envelope/"><e:Body><e:Fault/></e:Body></e:Envelope>'
    assert is_fault(fault)
    assert not is_fault(answer)
