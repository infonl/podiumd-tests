"""Archiving properties of PDFs the platform generates."""

from __future__ import annotations

import io

import pikepdf

FONT_FILES = ("/FontFile", "/FontFile2", "/FontFile3")


def pdfa_problems(content: bytes, part: str = "2", conformance: str = "B") -> list[str]:
    """Return why the PDF is no PDF/A-<part><conformance> with PDF/UA: its XMP claims and fonts; [] when none.

    Checks what the PDF declares and that every font is embedded, no full validation (veraPDF).
    """
    with pikepdf.open(io.BytesIO(content)) as pdf:
        meta = pdf.open_metadata()
        declared = {key: meta.get(key) for key in ("pdfaid:part", "pdfaid:conformance", "pdfuaid:part")}
        missing = [str(obj.get("/FontName")) for obj in pdf.objects if _is_unembedded_font(obj)]
    wanted = {"pdfaid:part": part, "pdfaid:conformance": conformance, "pdfuaid:part": "1"}
    wrong = {key: value for key, value in wanted.items() if declared[key] != value}
    problems = [f"XMP {key} is {declared[key]!r}, not {value!r}" for key, value in wrong.items()]
    return problems + [f"font {name} is not embedded" for name in missing]


def _is_unembedded_font(obj: object) -> bool:
    """Return whether the PDF object is a font descriptor without a font file."""
    if not isinstance(obj, pikepdf.Dictionary) or obj.get("/Type") != pikepdf.Name.FontDescriptor:
        return False
    return not any(key in obj for key in FONT_FILES)
