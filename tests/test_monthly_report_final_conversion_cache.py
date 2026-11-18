"""A35: synthetic final-conversion reuse and fail-closed boundaries.

The real-Office control uses a generated report with no client data. These
tests do not claim authentic-source or served-browser acceptance.
"""
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from time import perf_counter, process_time
from types import SimpleNamespace

import pymupdf as fitz
import pytest
from PIL import Image

from app import monthly_report_docx as output
from app import monthly_report_final_conversion_cache as cache
from app import monthly_report_render_jobs as jobs
from app.monthly_report_model import ReportPeriod, ResolvedBlock, synthetic_draft, synthetic_profiles
from app.monthly_report_asset_review import approve_all_assets
from tests.conftest import requires_libreoffice


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    cache.clear()
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(output.pdf_converter, "OUTPUT_DIR", tmp_path)
    # Explicitly model a healthy 512-MiB cgroup for deterministic cache tests.
    monkeypatch.setattr(jobs, "memory_headroom", lambda: 512 * 1024 * 1024)
    yield
    cache.clear()


@pytest.fixture
def draft():
    return synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9))


@pytest.fixture
def backend(monkeypatch, tmp_path):
    calls = []
    def convert(path, *, wait_seconds, lossless_images):
        assert lossless_images is True and wait_seconds == 130
        calls.append(sha256(path.read_bytes()).hexdigest())
        result = tmp_path / (path.stem + ".pdf")
        with fitz.open() as pdf:
            pdf.new_page().insert_text((72, 72), "A35 synthetic report")
            pdf.save(result)
        return result
    monkeypatch.setattr(jobs, "convert_to_pdf", convert)
    return calls


def generate(draft, *, owner="visitor-A", assets=()):
    return output.generate_report(
        draft, acknowledged_fingerprint=draft.fingerprint,
        reuse_owner=owner, reuse_asset_versions=assets,
    )


def test_persisted_and_reloaded_revision_keeps_same_content(draft, backend):
    from app import monthly_report_library as library
    saved = library.save_snapshot(draft, expected_revision=0, entered_editor=draft.prepared_by)
    loaded = library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period)
    assert loaded.revision == saved.revision
    assert loaded.draft == draft
    first = generate(loaded.draft)
    second = generate(loaded.draft)
    assert first.docx == second.docx and first.pdf == second.pdf
    assert len(backend) == 1
    reloaded = library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period)
    assert reloaded.draft == draft and reloaded.revision == saved.revision


def test_same_immutable_report_reuses_one_conversion_and_identical_bytes(draft, backend):
    first = generate(draft)
    second = generate(draft)
    assert len(backend) == 1
    assert first.docx == second.docx and first.pdf == second.pdf
    assert first.pdf.startswith(b"%PDF-")
    assert sha256(first.docx).hexdigest() == sha256(second.docx).hexdigest()
    assert sha256(first.pdf).hexdigest() == sha256(second.pdf).hexdigest()
    with fitz.open(stream=second.pdf, filetype="pdf") as pages:
        assert len(pages) == 1


@pytest.mark.parametrize("dimension", ("owner", "site", "month", "activity", "logo"))
def test_different_owner_site_month_activity_or_logo_reconverts(draft, backend, dimension):
    first = generate(draft)
    assert first.pdf
    next_draft, owner, assets = draft, "visitor-A", ()
    if dimension == "owner":
        owner = "visitor-B"
    elif dimension == "site":
        profile = replace(draft.profile, key=draft.profile.key + "-elsewhere")
        next_draft = replace(draft, profile=profile)
    elif dimension == "month":
        next_draft = replace(draft, period=ReportPeriod(2026, 10))
    elif dimension == "activity":
        blocks = tuple(replace(block, rows=(("Synthetic Activity row: completed",),))
                       if block.key == "demo_activity" else block for block in draft.blocks)
        next_draft = replace(draft, blocks=blocks)
    else:
        # Same labelled unsaved logo, changed pixels: no digest aliasing.
        assets = (("client-logo.png", sha256(b"changed synthetic pixels").digest()),)
    second = generate(next_draft, owner=owner, assets=assets)
    assert second.pdf
    assert len(backend) == 2



def _logo(color):
    stream = BytesIO()
    Image.new("RGB", (80, 30), color).save(stream, "PNG")
    return stream.getvalue()


def test_changed_actual_client_logo_recomputes_and_preserves_source_bytes(draft, backend):
    first, second = _logo((60, 130, 160)), _logo((160, 80, 30))
    a, b = (sha256(raw).hexdigest() + ".png" for raw in (first, second))
    assets = {a: first, b: second}
    def with_logo(ref):
        logo = approve_all_assets(ResolvedBlock("client_logo", "Library", asset_hashes=(ref,)))
        return replace(draft, blocks=tuple(block for block in draft.blocks if block.key != "client_logo") + (logo,))
    one = with_logo(a)
    two = with_logo(b)
    report_a = output.generate_report(one, acknowledged_fingerprint=one.fingerprint,
                                      asset_loader=assets.__getitem__, reuse_owner="visitor-A")
    report_b = output.generate_report(two, acknowledged_fingerprint=two.fingerprint,
                                      asset_loader=assets.__getitem__, reuse_owner="visitor-A")
    assert report_a.pdf and report_b.pdf
    assert len(backend) == 2 and report_a.docx != report_b.docx
    assert assets == {a: first, b: second}


def test_missing_logo_fails_instead_of_reusing_previous_artifact(draft, backend):
    valid = _logo((60, 130, 160))
    ref = sha256(valid).hexdigest() + ".png"
    logo = approve_all_assets(ResolvedBlock("client_logo", "Library", asset_hashes=(ref,)))
    with_logo = replace(draft, blocks=(*draft.blocks, logo))
    assert output.generate_report(with_logo, asset_loader={ref: valid}.__getitem__,
                                  reuse_owner="visitor-A").pdf
    with pytest.raises(KeyError):
        output.generate_report(with_logo, asset_loader={}.__getitem__, reuse_owner="visitor-A")
    assert len(backend) == 1


def test_privacy_sanitizers_execute_again_on_identical_hit(draft, backend, monkeypatch):
    from app import monthly_report_media_privacy as privacy
    original_media = privacy.sanitize_package_media
    original_alpha = privacy.sanitize_package_transparency
    called = {"media": 0, "alpha": 0}
    def media(raw):
        called["media"] += 1
        return original_media(raw)
    def alpha(raw):
        called["alpha"] += 1
        return original_alpha(raw)
    monkeypatch.setattr(privacy, "sanitize_package_media", media)
    monkeypatch.setattr(privacy, "sanitize_package_transparency", alpha)
    assert generate(draft).pdf
    assert generate(draft).pdf
    assert called["media"] >= 2 and called["alpha"] >= 2
    assert len(backend) == 1

def test_without_owner_or_revision_never_reuses(draft, backend):
    for _ in range(2):
        assert generate(draft, owner=None).pdf
    assert len(backend) == 2
    assert cache.read(("converter",)) is None
    with cache.owner_scope("visitor-A", ("contract", "site", "2026-09")):
        assert cache.read(("converter",)) is None


def test_pinned_design_validation_executes_on_cache_hit(draft, backend, monkeypatch):
    from app import monthly_report_designs as designs
    assert generate(draft).pdf
    monkeypatch.setattr(
        designs, "source_for",
        lambda profile: (_ for _ in ()).throw(ValueError("Pinned design verification failed")))
    with pytest.raises(ValueError, match="Pinned design verification failed"):
        generate(draft)
    assert len(backend) == 1


def test_preflight_runs_on_hit_and_blocks_newly_invalid_report(draft, backend, monkeypatch):
    assert generate(draft).pdf
    ordinary = output.preflight
    seen = []
    def reject_next(*args, **kwargs):
        seen.append(True)
        return [SimpleNamespace(blocking=True, message="Synthetic preflight changed", code="synthetic")]
    monkeypatch.setattr(output, "preflight", reject_next)
    with pytest.raises(ValueError, match="Synthetic preflight changed"):
        generate(draft)
    monkeypatch.setattr(output, "preflight", ordinary)
    assert seen and len(backend) == 1
    assert generate(draft).pdf and len(backend) == 1


def test_source_receipt_and_acknowledgement_identity_change_cannot_hit(draft, backend):
    # Exercise the conversion layer directly with evidence that has already
    # passed its authoritative operation gate in _generate_verified_report.
    raw = output.assemble_docx(draft, acknowledged_fingerprint=draft.fingerprint)
    scope = (draft.profile.contract, draft.profile.key, draft.period.key)
    versions = ()
    with cache.owner_scope("visitor-A", scope, versions):
        with cache.verified_revision((draft.fingerprint, "ack-A", "manifest-A", "receipt-A", "art-A")):
            assert output._convert_report_pdf(draft, raw)[0]
            assert output._convert_report_pdf(draft, raw)[0]
        with cache.verified_revision((draft.fingerprint, "ack-A", "manifest-B", "receipt-A", "art-A")):
            assert output._convert_report_pdf(draft, raw)[0]
        with cache.verified_revision((draft.fingerprint, "ack-B", "manifest-B", "receipt-A", "art-A")):
            assert output._convert_report_pdf(draft, raw)[0]
    assert len(backend) == 3


def test_invalid_or_failed_pdf_is_never_cached(draft, monkeypatch, tmp_path):
    attempts = []
    def broken(path, **kwargs):
        attempts.append(len(attempts))
        target = tmp_path / (path.stem + ".pdf")
        target.write_bytes(b"not-a-pdf")
        return target
    monkeypatch.setattr(jobs, "convert_to_pdf", broken)
    for _ in range(2):
        result = generate(draft)
        assert result.docx and result.pdf is None and result.pdf_error
    assert len(attempts) == 2


def test_entry_expiry_budget_and_memory_pressure(monkeypatch):
    clock = [100.]
    monkeypatch.setattr(cache, "monotonic", lambda: clock[0])
    scope = ("contract", "site", "2026-09")
    with cache.owner_scope("visitor-A", scope), cache.verified_revision(("rev", "ack", "manifest")):
        cache.remember(("input",), b"%PDF-small")
        assert cache.read(("input",)) == b"%PDF-small"
        clock[0] += cache.TTL_SECONDS + 1
        assert cache.read(("input",)) is None
        cache.remember(("input",), b"%PDF-" + b"a" * cache.MAX_ENTRY_BYTES)
        assert cache.read(("input",)) is None
        monkeypatch.setattr(jobs, "memory_headroom", lambda: jobs.PREVIEW_HEADROOM_BYTES)
        cache.remember(("input",), b"%PDF-small")
        assert cache.read(("input",)) is None
    assert cache.read(("input",)) is None


@requires_libreoffice
def test_actual_libreoffice_cold_warm_and_changed_activity(draft, monkeypatch):
    real = jobs.convert_to_pdf
    conversions = []
    def count(path, **kwargs):
        conversions.append(sha256(path.read_bytes()).hexdigest())
        return real(path, **kwargs)
    monkeypatch.setattr(jobs, "convert_to_pdf", count)

    before_cpu, before_wall = process_time(), perf_counter()
    first = generate(draft)
    cold_wall = perf_counter() - before_wall
    cold_cpu = process_time() - before_cpu
    assert first.pdf, first.pdf_error
    before_cpu, before_wall = process_time(), perf_counter()
    warm = generate(draft)
    warm_wall = perf_counter() - before_wall
    warm_cpu = process_time() - before_cpu
    assert first.docx == warm.docx and first.pdf == warm.pdf
    assert len(conversions) == 1
    with fitz.open(stream=first.pdf, filetype="pdf") as original:
        with fitz.open(stream=warm.pdf, filetype="pdf") as repeated:
            assert len(original) == len(repeated)
            assert [tuple(p.rect) for p in original] == [tuple(p.rect) for p in repeated]
    changed = replace(draft, blocks=tuple(
        replace(block, text=block.text + " Inspection confirmed.")
        if block.key == "demo_activity" else block for block in draft.blocks))
    edited = generate(changed)
    assert edited.pdf, edited.pdf_error
    assert len(conversions) == 2
    assert first.docx != edited.docx
    print(f"A35 LibreOffice synthetic cold={cold_wall:.3f}s wall/{cold_cpu:.3f}s cpu "
          f"warm={warm_wall:.3f}s wall/{warm_cpu:.3f}s cpu, conversions=1")
