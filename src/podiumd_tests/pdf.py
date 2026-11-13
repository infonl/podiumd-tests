"""Archiving and accessibility properties of PDFs the platform generates."""

from __future__ import annotations

import io
import json
import shutil
import tempfile

from pathlib import Path
from typing import TYPE_CHECKING
from typing import cast

import pikepdf

from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.process import ProcessError
from podiumd_tests.process import run_checked
from podiumd_tests.process import run_process

if TYPE_CHECKING:
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.process import Runner

FONT_FILES = ("/FontFile", "/FontFile2", "/FontFile3")
CLAIMS = ("pdfaid:part", "pdfaid:conformance", "pdfuaid:part")
VERAPDF_IMAGE = "verapdf/cli:v1.30.3"
VERAPDF_TIMEOUT = 180
# veraPDF exits 1 for a PDF that is not compliant.
VERAPDF_EXITS = (0, 1)


def pdfa_problems(content: bytes, part: str = "2", conformance: str = "B") -> list[str]:
    """Return why the PDF is no PDF/A-<part><conformance> with PDF/UA: its XMP claims and fonts; [] when none.

    Checks what the PDF declares and that every font is embedded, no full validation (verapdf_failures).
    """
    with pikepdf.open(io.BytesIO(content)) as pdf:
        declared = _claims(pdf)
        missing = [str(obj.get("/FontName")) for obj in pdf.objects if _is_unembedded_font(obj)]
    wanted = {"pdfaid:part": part, "pdfaid:conformance": conformance, "pdfuaid:part": "1"}
    wrong = {key: value for key, value in wanted.items() if declared[key] != value}
    problems = [f"XMP {key} is {declared[key]!r}, not {value!r}" for key, value in wrong.items()]
    return problems + [f"font {name} is not embedded" for name in missing]


def claimed_flavours(content: bytes) -> list[str]:
    """Return the veraPDF flavours the PDF's XMP claims, e.g. ["2b", "ua1"]."""
    with pikepdf.open(io.BytesIO(content)) as pdf:
        declared = _claims(pdf)
    part, conformance, ua = (declared[key] or "" for key in CLAIMS)
    pdfa = f"{part}{conformance.lower()}" if part else ""
    pdfua = f"ua{ua}" if ua else ""
    return [flavour for flavour in (pdfa, pdfua) if flavour]


def _claims(pdf: pikepdf.Pdf) -> dict[str, str | None]:
    meta = pdf.open_metadata()
    return {key: meta.get(key) for key in CLAIMS}


def _is_unembedded_font(obj: object) -> bool:
    """Return whether the PDF object is a font descriptor without a font file."""
    if not isinstance(obj, pikepdf.Dictionary) or obj.get("/Type") != pikepdf.Name.FontDescriptor:
        return False
    return not any(key in obj for key in FONT_FILES)


def _verapdf(folder: str) -> list[str]:
    """Return the veraPDF command: the CLI on PATH, else its Docker image with the folder at the same path."""
    local = shutil.which("verapdf")
    if local:
        return [local]
    return ["docker", "run", "--rm", "--network", "none", "-v", f"{folder}:{folder}:ro", VERAPDF_IMAGE]


def verapdf_unavailable(runner: Runner = run_process) -> str:
    """Return why veraPDF cannot run here; "" when it can."""
    try:
        run_checked(runner, [*_verapdf(tempfile.gettempdir()), "--version"], VERAPDF_TIMEOUT)
    except ProcessError as exc:
        return f"veraPDF unavailable ({exc}): put `verapdf` on PATH or let Docker run {VERAPDF_IMAGE}"
    return ""


def verapdf_report(content: bytes, runner: Runner = run_process) -> dict[str, list[str]]:
    """Return veraPDF's failed rules per flavour the PDF claims, e.g. {"2b": [], "ua1": [...]}."""
    return {flavour: verapdf_failures(content, flavour, runner) for flavour in claimed_flavours(content)}


def verapdf_failures(content: bytes, flavour: str, runner: Runner = run_process) -> list[str]:
    """Return the rules of the flavour ("2b", "ua1") the PDF fails in veraPDF; [] when it is compliant."""
    with tempfile.TemporaryDirectory() as folder:
        # The Docker image runs as another user.
        Path(folder).chmod(0o755)
        path = Path(folder) / "document.pdf"
        path.write_bytes(content)
        path.chmod(0o644)
        command = [*_verapdf(folder), "--format", "json", "--flavour", flavour, str(path)]
        report = json.loads(run_checked(runner, command, VERAPDF_TIMEOUT, accept=VERAPDF_EXITS))
    jobs = entries(section(cast("JsonObject", report), "report").get("jobs"))
    results = [result for job in jobs for result in entries(job.get("validationResult"))]
    if not results:
        return [f"veraPDF validated nothing: {report}"]
    return [_summary(rule) for result in results for rule in _failed_rules(result)]


def _failed_rules(result: JsonObject) -> list[JsonObject]:
    rules = entries(section(result, "details").get("ruleSummaries"))
    return [rule for rule in rules if rule.get("status") == "failed"]


def _summary(rule: JsonObject) -> str:
    """'<specification> <clause>-<test>: <description> (<n> checks)'."""
    where = f"{rule.get('specification')} {rule.get('clause')}-{rule.get('testNumber')}"
    return f"{where}: {rule.get('description')} ({rule.get('failedChecks')} checks)"
