"""Cross-process deterministic source construction without live application writes."""
from io import BytesIO
from pathlib import Path
import hashlib
import json
import subprocess
import sys

from docx import Document
import pymupdf
from PIL import Image
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.qa_monthly_host_deterministic import (
    canonical_docx, canonical_pdf, deterministic_noise, stable_pdf_bytes,
)


def _sample():
    doc = Document()
    doc.add_paragraph('Synthetic report. No customer data.')
    image = deterministic_noise((220, 130), 24, ordinal=0).convert('RGB')
    jpeg = BytesIO()
    image.save(jpeg, format='JPEG')
    doc.add_picture(BytesIO(jpeg.getvalue()))
    out = BytesIO()
    doc.save(out)
    word = canonical_docx(out.getvalue())
    pdf = pymupdf.open()
    pdf.new_page().insert_text((40, 50), 'Invented data')
    raw = canonical_pdf(stable_pdf_bytes(pdf.tobytes))
    with pymupdf.open(stream=raw, filetype='pdf') as reopened:
        assert len(reopened) == 1 and 'Invented data' in reopened[0].get_text()
    assert Document(BytesIO(word)).paragraphs[0].text == 'Synthetic report. No customer data.'
    return {'docx': hashlib.sha256(word).hexdigest(), 'pdf': hashlib.sha256(raw).hexdigest()}


def test_synthetic_docx_pdf_repeatable_and_still_reopen():
    assert _sample() == _sample()


def test_seed_distinguishes_images_without_random_process_state():
    one = deterministic_noise((40, 30), 24, ordinal=0).tobytes()
    assert one == deterministic_noise((40, 30), 24, ordinal=0).tobytes()
    assert one != deterministic_noise((40, 30), 24, ordinal=1).tobytes()


def test_process_independence_and_no_customer_files():
    path = str(Path(__file__).resolve().parents[1])
    code = '''
import hashlib,io,json,sys
sys.path.insert(0,sys.argv[1])
from docx import Document
import pymupdf
from scripts.qa_monthly_host_deterministic import canonical_docx,canonical_pdf,deterministic_noise,stable_pdf_bytes
a=Document(); a.add_paragraph('synthetic'); b=io.BytesIO();a.save(b)
p=pymupdf.open();p.new_page().insert_text((40,50),'invented')
print(json.dumps({'word':hashlib.sha256(canonical_docx(b.getvalue())).hexdigest(),'pdf':hashlib.sha256(canonical_pdf(stable_pdf_bytes(p.tobytes))).hexdigest(),'noise':hashlib.sha256(deterministic_noise((100,80),24,ordinal=0).tobytes()).hexdigest()}))
'''
    results = [subprocess.check_output([sys.executable, '-c', code, path], text=True) for _ in range(2)]
    assert json.loads(results[0]) == json.loads(results[1])


# MuPDF's two observed /ID encodings for the same one-page synthetic PDF tail.
_HEX_TAIL = (b"trailer\n<</Size 6/Root 1 0 R/ID[<54C293336A40537145C2A572C2BA5EC2>"
             b"<0F2D7A1B3C4D5E6F708192A3B4C5D6E7>]>>\nstartxref\n522\n%%EOF\n")
_LITERAL_TAIL = (b"trailer\n<</Size 6/Root 1 0 R/ID[<54C293336A40537145C2A572C2BA5EC2>"
                 b"(\\317!\\0131~\\).51$eM\\273\\205>\\204)]>>\nstartxref\n522\n%%EOF\n")


def test_literal_string_trailer_id_is_regenerated_not_rejected():
    """About one MuPDF save in eighty writes the second ID as a literal string."""
    with pytest.raises(ValueError, match="exactly one trailer ID pair"):
        canonical_pdf(_LITERAL_TAIL)
    saves = iter((_LITERAL_TAIL, _LITERAL_TAIL, _HEX_TAIL))
    raw = stable_pdf_bytes(lambda: next(saves))
    assert raw == _HEX_TAIL
    assert b"/ID[<0123456789ABCDEF0123456789ABCDEF><FEDCBA9876543210FEDCBA9876543210>]" in canonical_pdf(raw)
    assert len(canonical_pdf(raw)) == len(raw)
    with pytest.raises(ValueError, match="exactly one trailer ID pair"):
        stable_pdf_bytes(lambda: _LITERAL_TAIL, attempts=3)


def test_many_real_saves_all_canonicalize():
    pdf = pymupdf.open()
    pdf.new_page().insert_text((40, 50), "Invented data")
    first = canonical_pdf(stable_pdf_bytes(pdf.tobytes))
    assert all(canonical_pdf(stable_pdf_bytes(pdf.tobytes)) == first for _ in range(400))
