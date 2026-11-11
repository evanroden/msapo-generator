"""P7: pre-generation ranges are not internal preflight or completed bytes."""
from app.monthly_report_size_forecast import forecast_output_sizes, format_size_range
from app.monthly_report_docx import ReportPackage
from app import monthly_report_guided as guided
from test_monthly_report_ui import monthly


def test_historical_underestimates_and_capped_native_sample_are_inside_wide_ranges():
    samples = (
        (1_000_000, 5_200_000, 4_200_000),
        (1_900_000, 6_000_000, 4_600_000),
        (13_630_812, 13_613_736, 2_642_403),
    )
    for input_bytes, word_bytes, pdf_bytes in samples:
        forecast = forecast_output_sizes(input_bytes, libreoffice_available=True)
        assert forecast.word.low <= word_bytes <= forecast.word.high
        assert forecast.pdf.low <= pdf_bytes <= forecast.pdf.high
        assert forecast.word != forecast.pdf
        assert 'MB' in format_size_range(forecast.word)


def test_unavailable_source_converter_and_out_of_calibration_are_explicit():
    assert forecast_output_sizes(100_000, sources_ready=False).word is None
    assert forecast_output_sizes(100_000, sources_ready=False).pdf is None
    assert forecast_output_sizes(100_000, libreoffice_available=False).word is not None
    assert forecast_output_sizes(100_000, libreoffice_available=False).pdf is None
    assert forecast_output_sizes(100_000, pdf_backend='gotenberg').pdf is None
    for invalid in (None, 0, -1, True, 129 * 1024 * 1024):
        forecast = forecast_output_sizes(invalid, libreoffice_available=True)
        assert forecast.word is None and forecast.pdf is None
    assert format_size_range(None) == 'unavailable'


def test_forecast_does_not_call_assembly_or_conversion(monkeypatch):
    from app import monthly_report_docx as docx
    def forbidden(*args, **kwargs):
        raise AssertionError('No hidden report assembly/conversion to estimate size')
    monkeypatch.setattr(docx, 'generate_report', forbidden)
    monkeypatch.setattr(docx, 'assemble_docx', forbidden)
    out = forecast_output_sizes(2_000_000, libreoffice_available=True)
    assert out.word and out.pdf


def test_before_create_and_current_revision_only_actual_after_create(monkeypatch, tmp_path):
    calls = []
    def fake(draft, **kwargs):
        calls.append(draft.fingerprint)
        return ReportPackage(b'PK-SYNTHETIC', b'%PDF-SYNTHETIC',
                             'synthetic.docx', 'synthetic.pdf', draft.fingerprint)
    monkeypatch.setattr(guided, 'generate_report', fake)
    app = monthly(monkeypatch, tmp_path)
    assert not app.exception
    assert calls == []
    initial = [c.value for c in app.caption]
    assert any('Before creation · Word estimate:' in c and 'PDF estimate:' in c for c in initial)
    assert not any('Actual Word (DOCX):' in c for c in initial)
    next(w for w in app.text_input if w.label == 'Prepared by').set_value('Synthetic Editor').run()
    assert calls == []
    next(w for w in app.button if w.label == 'Create Word and PDF').click().run()
    assert not app.exception
    assert len(calls) == 1
    completed = [c.value for c in app.caption]
    assert any('Actual Word (DOCX):' in c and 'Actual PDF:' in c for c in completed)
    assert not any('Before creation · Word estimate:' in c for c in completed)
    next(w for w in app.text_area if w.label == 'Activity summary').set_value(
        'Synthetic updated content for this new revision.').run()
    assert not app.exception
    assert calls == [calls[0]]  # no implicit regeneration after an edit
    revised = [c.value for c in app.caption]
    assert any('Before creation · Word estimate:' in c for c in revised)
    assert not any('Actual Word (DOCX):' in c for c in revised)
