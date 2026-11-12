"""pdfa_problems on PDFs built in memory."""

import io

import pikepdf

from podiumd_tests.pdf import pdfa_problems


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


def test_pdfa_with_embedded_fonts_has_no_problems():
    assert pdfa_problems(pdf_bytes(PDFA2B_UA, embedded=True)) == []


def test_missing_claims_and_fonts_are_named():
    problems = pdfa_problems(pdf_bytes({"pdfaid:part": "1", "pdfaid:conformance": "B"}, embedded=False))
    assert problems == [
        "XMP pdfaid:part is '1', not '2'",
        "XMP pdfuaid:part is None, not '1'",
        "font /Liberation is not embedded",
    ]
