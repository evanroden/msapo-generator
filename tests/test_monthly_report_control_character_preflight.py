"""Classify the four #296 probes without claiming all controls crash Word."""
from dataclasses import replace
from io import BytesIO

from docx import Document
import pytest

from app.monthly_report_checks import preflight
from app.monthly_report_docx import _build_docx, assemble_docx
from app.monthly_report_model import ReportPeriod, synthetic_draft, synthetic_profiles
from app.monthly_report_native_layout import build_native_docx
from test_monthly_report_designs import master_reference


def draft_with(character):
    draft = synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 10))
    block = replace(draft.blocks[0], text="Before" + character + "After")
    return replace(draft, blocks=(block, *draft.blocks[1:]))


@pytest.mark.parametrize("mode", ["plain", "native", "master"])
@pytest.mark.parametrize("character", ["\x0b", "\x0c", "\x07", "\ufffe"])
def test_probe_classification_and_actionable_preflight(tmp_path, mode, character):
    draft = draft_with(character)
    def render():
        if mode == "plain":
            return _build_docx(draft)
        return build_native_docx(draft, master_reference(tmp_path), master=mode == "master")
    checks = [c for c in preflight(draft) if c.code == "text_character"]
    if character in ("\x07", "\ufffe"):
        # Bypassing the public gate retains the exact observed failing boundary.
        with pytest.raises(ValueError, match="XML compatible"):
            render()
        assert len(checks) == 1
        assert checks[0].blocking and checks[0].block_key == draft.blocks[0].key
        assert f"U+{ord(character):04X}" in checks[0].message
    else:
        assert not checks
        doc = Document(BytesIO(render()))
        text = "\n".join(p.text for p in doc.paragraphs)
        assert "Before\nAfter" in text


def test_public_generation_names_the_editor_before_xml_assembly():
    draft = draft_with("\x07")
    with pytest.raises(ValueError, match="U\\+0007") as error:
        assemble_docx(draft, acknowledged_fingerprint=draft.fingerprint)
    assert "XML compatible" not in str(error.value)


def test_omitted_content_is_recoverable_and_valid_unicode_is_allowed():
    draft = draft_with("\x07")
    omitted = replace(draft, blocks=(replace(draft.blocks[0], source="Omit"), *draft.blocks[1:]))
    assert not [c for c in preflight(omitted) if c.code == "text_character"]
    assert not [c for c in preflight(draft_with("\t\n\r café — 漢字 😀")) if c.code == "text_character"]
