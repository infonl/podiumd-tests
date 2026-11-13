"""pdfa_problems, claimed_flavours and the veraPDF report on PDFs built in memory."""

import io
import json
import subprocess

import pikepdf

from podiumd_tests.pdf import VERAPDF_IMAGE
from podiumd_tests.pdf import claimed_flavours
from podiumd_tests.pdf import pdfa_problems
from podiumd_tests.pdf import verapdf_failures
from podiumd_tests.pdf import verapdf_report
from podiumd_tests.pdf import verapdf_unavailable


def pdf_bytes(claims: dict[str, str], *, embedded: bool) -> bytes:
    pdf = pikepdf.new()
    pdf.add_blank_page()
    with pdf.open_metadata(set_pikepdf_as_editor=False) as meta:
        meta.update(claims)
    descriptor = pikepdf.Dictionary(Type=pikepdf.Name.FontDescriptor, FontName=pikepdf.Name("/Liberation"))
    if embedded:
        descriptor.FontFile2 = pdf.make_stream(b"font")
    font = pikepdf.Dictionary(Type=pikepdf.Name.Font, FontDescriptor=pdf.make_indirect(descriptor))
    pdf.pages[0].Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font))
    out = io.BytesIO()
    pdf.save(out)
    return out.getvalue()


PDFA2B_UA = {"pdfaid:part": "2", "pdfaid:conformance": "B", "pdfuaid:part": "1"}
WHICH = "podiumd_tests.pdf.shutil.which"


def test_pdfa_with_embedded_fonts_has_no_problems():
    assert pdfa_problems(pdf_bytes(PDFA2B_UA, embedded=True)) == []


def test_missing_claims_and_fonts_are_named():
    problems = pdfa_problems(pdf_bytes({"pdfaid:part": "1", "pdfaid:conformance": "B"}, embedded=False))
    assert problems == [
        "XMP pdfaid:part is '1', not '2'",
        "XMP pdfuaid:part is None, not '1'",
        "font /Liberation is not embedded",
    ]


def verapdf_json(*rules):
    """veraPDF's JSON report of one PDF with these rule summaries."""
    details = {"ruleSummaries": list(rules)}
    return json.dumps({"report": {"jobs": [{"validationResult": [{"compliant": not rules, "details": details}]}]}})


FAILED_RULE = {
    "specification": "ISO 14289-1:2014",
    "clause": "7.1",
    "testNumber": 10,
    "status": "failed",
    "failedChecks": 2,
    "description": "DisplayDocTitle shall be true",
}


class Answering:
    """A runner that answers every command with this exit code and stdout; records the commands."""

    def __init__(self, code: int, out: str) -> None:
        self.code: int = code
        self.out: str = out
        self.calls: list[list[str]] = []

    def __call__(self, args, _timeout, _stdin=None):
        self.calls.append(list(args))
        return subprocess.CompletedProcess(list(args), self.code, self.out, "")


def test_claimed_flavours_are_the_xmp_claims():
    assert claimed_flavours(pdf_bytes(PDFA2B_UA, embedded=True)) == ["2b", "ua1"]
    assert claimed_flavours(pdf_bytes({"pdfuaid:part": "1"}, embedded=True)) == ["ua1"]


def test_a_non_compliant_pdf_names_its_failed_rules(monkeypatch):
    monkeypatch.setattr(WHICH, lambda name: f"/usr/bin/{name}")
    run = Answering(1, verapdf_json(FAILED_RULE, {**FAILED_RULE, "status": "passed"}))
    rule = "ISO 14289-1:2014 7.1-10: DisplayDocTitle shall be true (2 checks)"
    assert verapdf_report(pdf_bytes(PDFA2B_UA, embedded=True), run) == {"2b": [rule], "ua1": [rule]}
    assert run.calls[0][:5] == ["/usr/bin/verapdf", "--format", "json", "--flavour", "2b"]


def test_a_compliant_pdf_has_no_failures_and_docker_runs_without_network(monkeypatch):
    monkeypatch.setattr(WHICH, lambda _name: None)
    run = Answering(0, verapdf_json())
    assert verapdf_failures(b"%PDF", "ua1", run) == []
    assert run.calls[0][:5] == ["docker", "run", "--rm", "--network", "none"]
    assert VERAPDF_IMAGE in run.calls[0]


def test_a_report_without_result_is_a_failure():
    run = Answering(0, '{"report": {"jobs": [{}]}}')
    assert verapdf_failures(b"%PDF", "ua1", run) == ["veraPDF validated nothing: {'report': {'jobs': [{}]}}"]


def test_verapdf_unavailable_names_the_missing_command():
    def missing(args, _timeout, _stdin=None):
        raise FileNotFoundError(args[0])

    assert "not found on PATH" in verapdf_unavailable(missing)
    assert not verapdf_unavailable(Answering(0, "veraPDF 1.30.3"))
