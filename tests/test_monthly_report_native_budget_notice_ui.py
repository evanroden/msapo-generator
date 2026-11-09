"""Synthetic Starting Report journeys distinguish processing limits from damage.

The real uploader handler, inspector, native-rendition budget checks and review
controls run under AppTest. Only file selection and explicitly named fault
controls are injected; no browser, rendered Word/PDF or production claim.
"""
from hashlib import sha256
from zipfile import ZipFile, ZIP_DEFLATED

import pytest

from app import monthly_report_compatibility_view as compatibility
from app import monthly_report_library as library
from app import monthly_report_source_view_runtime as runtime
from app.monthly_report_import import inspect_docx, MAX_DOCX_BYTES
from app.monthly_report_model import synthetic_profiles
from test_monthly_report_source_frame_logo_role import source, mutate
from test_monthly_report_start_import import start_app


def _source(tmp_path, *, mutation=None):
    # Identical alternatives are already readable and never enter this route.
    path = source(tmp_path, divergent=True, shared_outside=False, mutation=mutation)
    assert runtime.import_candidate(inspect_docx(path))
    return path


def _confirm_source_site(app):
    # The synthetic source uses an alternate cover spelling. Make the actual
    # site decision instead of bypassing the membership gate in session state.
    choices = [control for control in app.checkbox
               if control.key.endswith("_source_site_north")]
    if choices:
        assert len(choices) == 1
        choices[0].check().run()
    assert not app.exception
    return app


def _assert_preserved_and_blocked(app, path, original, inspection):
    assert not app.exception
    stages = [value for key, value in app.session_state.filtered_state.items()
              if key.endswith("_stage")]
    assert len(stages) == 1
    assert stages[0][1].read_bytes() == path.read_bytes() == original
    assert stages[0][2] == inspection
    assert stages[0][2].sha256 == sha256(original).hexdigest()
    controls = [button for button in app.button
                if button.label == "Continue to this month’s updates"]
    assert controls and all(button.disabled for button in controls)
    assert not library.list_profiles(synthetic_profiles()[0].contract)


def _warnings(app):
    return "\n".join(warning.value for warning in app.warning)


def _require_processing_guidance(app):
    warning = _warnings(app)
    assert "processing limit" in warning
    assert "not evidence that the artwork is damaged" in warning
    assert "original and current review are unchanged" in warning
    assert "independent template" in warning
    assert "smaller test copy" in warning
    assert "Replacing the upload starts a new review" in warning
    assert any("native-artwork processing limit" in error.value for error in app.error)
    assert not any("Repair that artwork in the original Word file" in error.value
                   for error in app.error)
    return warning


@pytest.mark.parametrize("kind,limit,label", (
    ("expanded", "512 KiB", "package expansion"),
    ("xml", "512 KiB", "XML byte"),
    ("media", "128 bytes", "media byte"),
    ("nodes", "1,000 nodes", "XML complexity"),
    ("parts", "512 parts", "package part"),
    ("depth", "64 levels", "XML depth"),
))
def test_actual_native_budget_refusal_explains_binding_limit_without_losing_review(
        monkeypatch, tmp_path, kind, limit, label):
    path = _source(tmp_path)
    if kind == "parts":
        with ZipFile(path, "a", compression=ZIP_DEFLATED) as archive:
            for index in range(513 - len(archive.infolist())):
                archive.writestr(f"synthetic-budget/part-{index:04d}.bin", b"synthetic")
            assert len(archive.infolist()) == 513
    elif kind == "depth":
        with ZipFile(path, "a", compression=ZIP_DEFLATED) as archive:
            archive.writestr("customXml/synthetic-budget-depth.xml",
                             "<level>" * 65 + "synthetic" + "</level>" * 65)
    else:
        name, maximum = {
            "expanded": ("MAX_VIEW_EXPANDED_BYTES", 512 * 1024),
            "xml": ("MAX_VIEW_XML_BYTES", 512 * 1024),
            "media": ("MAX_VIEW_MEDIA_BYTES", 128),
            "nodes": ("MAX_VIEW_XML_NODES", 1000),
        }[kind]
        monkeypatch.setattr(compatibility, name, maximum)
    original = path.read_bytes()
    inspection = inspect_docx(path)
    assert runtime.import_candidate(inspection)
    assert len(original) < compatibility.MAX_VIEW_SOURCE_BYTES < MAX_DOCX_BYTES
    # Establish that these real bytes reach a current native processing guard,
    # independently of whatever text the UI later chooses to show.
    with pytest.raises(ValueError):
        runtime.derive_import_view(path, inspection)
    app = _confirm_source_site(start_app(monkeypatch, tmp_path, path))
    _assert_preserved_and_blocked(app, path, original, inspection)
    warning = _require_processing_guidance(app)
    assert label in warning and f"limit is {limit}" in warning
    assert "Observed " in warning
    # A passive rerun retains the exact staged source and the same diagnosis.
    app.run()
    _assert_preserved_and_blocked(app, path, original, inspection)
    assert _warnings(app) == warning


def test_compressed_source_notice_uses_the_exact_configured_binding_limit(monkeypatch, tmp_path):
    path = _source(tmp_path)
    original, inspection = path.read_bytes(), inspect_docx(path)
    monkeypatch.setattr(compatibility, "MAX_VIEW_SOURCE_BYTES", 32 * 1024)
    assert 32 * 1024 < len(original) < MAX_DOCX_BYTES
    app = _confirm_source_site(start_app(monkeypatch, tmp_path, path))
    _assert_preserved_and_blocked(app, path, original, inspection)
    warning = _require_processing_guidance(app)
    assert "limited to 32 KiB" in warning
    assert "128 MiB upload limit" in warning


def test_existing_24_mib_source_limit_notice_remains_available(monkeypatch, tmp_path):
    from scripts.workspace_cover_template_fallback import make_source
    path = make_source(tmp_path)
    original, inspection = path.read_bytes(), inspect_docx(path)
    assert compatibility.MAX_VIEW_SOURCE_BYTES == 24 * 1024 * 1024
    assert compatibility.MAX_VIEW_SOURCE_BYTES < len(original) < MAX_DOCX_BYTES
    assert runtime.import_candidate(inspection)
    app = _confirm_source_site(start_app(monkeypatch, tmp_path, path))
    _assert_preserved_and_blocked(app, path, original, inspection)
    warning = _require_processing_guidance(app)
    # The established full template-fallback journey depends on this wording.
    assert "limited to 24 MiB" in warning


def test_unsupported_native_artwork_is_not_relabelled_as_a_processing_limit(monkeypatch, tmp_path):
    path = _source(tmp_path, mutation=mutate("unknown"))
    original, inspection = path.read_bytes(), inspect_docx(path)
    with pytest.raises(ValueError) as refused:
        runtime.derive_import_view(path, inspection)
    app = _confirm_source_site(start_app(monkeypatch, tmp_path, path))
    _assert_preserved_and_blocked(app, path, original, inspection)
    warning = _warnings(app)
    assert "Automatic native artwork interpretation is blocked: " + str(refused.value) in warning
    assert "processing limit" not in warning
    assert any("Repair that artwork in the original Word file" in error.value
               for error in app.error)


@pytest.mark.parametrize("error", (
    ValueError("The staged original changed during automatic rendition analysis."),
    ValueError("Malformed native XML could not be read."),
    compatibility.CompatibilityError(
        "Native rendition is not proved: capability package expansion budget"),
), ids=("source-identity", "malformed-xml", "untyped-budget-wording"))
def test_nonbudget_derivation_errors_keep_existing_blocking_notice(monkeypatch, tmp_path, error):
    path = _source(tmp_path)
    original, inspection = path.read_bytes(), inspect_docx(path)

    def refuse(candidate, staged):
        # Inject only a post-inspection failure, not a resource-limit result.
        assert candidate.read_bytes() == original and staged == inspection
        raise error

    monkeypatch.setattr(runtime, "derive_import_view", refuse)
    app = _confirm_source_site(start_app(monkeypatch, tmp_path, path))
    _assert_preserved_and_blocked(app, path, original, inspection)
    warning = _warnings(app)
    assert "Automatic native artwork interpretation is blocked: " + str(error) in warning
    assert "processing limit" not in warning
    assert "independent template" not in warning and "smaller test copy" not in warning
    assert any("Repair that artwork in the original Word file" in item.value
               for item in app.error)
