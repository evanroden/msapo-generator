"""Native-art processing refusals name their actual binding limit and remain retryable."""

from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from app import monthly_report_compatibility_view as view
from app.monthly_report_upload_limits import byte_limit_label
from test_monthly_report_source_frame_logo_role import source


def measurements(raw):
    with ZipFile(BytesIO(raw)) as archive:
        infos = archive.infolist()
        xml = [info for info in infos if info.filename.endswith((".xml", ".rels"))]
        return {
            "MAX_VIEW_SOURCE_BYTES": len(raw),
            "MAX_VIEW_EXPANDED_BYTES": sum(info.file_size for info in infos),
            "MAX_VIEW_XML_BYTES": sum(info.file_size for info in xml),
            "MAX_VIEW_MEDIA_BYTES": sum(info.file_size for info in infos
                                        if info.filename.startswith("word/media/")),
            "MAX_VIEW_XML_NODES": sum(sum(1 for _ in ElementTree.fromstring(
                archive.read(info)).iter()) for info in xml),
        }


def assert_budget(error, label, observed, limit, unit="bytes"):
    # The existing parent class lets these regressions collect on unchanged main.
    assert isinstance(error, view.CompatibilityError)
    assert getattr(error, "budget", None) == label
    assert error.observed == observed and error.limit == limit and error.unit == unit
    actual = byte_limit_label(observed) if unit == "bytes" else f"{observed:,} {unit}"
    maximum = byte_limit_label(limit) if unit == "bytes" else f"{limit:,} {unit}"
    assert label in str(error)
    assert f"Observed {actual}; limit is {maximum}." in str(error)


@pytest.mark.parametrize("budget,label,unit", (
    ("MAX_VIEW_SOURCE_BYTES", "source byte budget", "bytes"),
    ("MAX_VIEW_EXPANDED_BYTES", "capability package expansion budget", "bytes"),
    ("MAX_VIEW_XML_BYTES", "capability XML byte budget", "bytes"),
    ("MAX_VIEW_MEDIA_BYTES", "capability cumulative media byte budget", "bytes"),
    ("MAX_VIEW_XML_NODES", "capability XML complexity budget", "nodes"),
))
def test_binding_budget_reports_exact_measurement_before_inspection_and_recovers(
        tmp_path, monkeypatch, budget, label, unit):
    path = source(tmp_path, divergent=True)
    original = path.read_bytes()
    successful = view.rederive_compatibility_view(path)
    receipt = successful.receipt_bytes
    observed = measurements(original)[budget]
    assert 1 < observed < getattr(view, budget)

    # Equal is allowed. The fixture lowers one cap; it never raises production limits.
    with monkeypatch.context() as exact:
        exact.setattr(view, budget, observed)
        assert view.rederive_compatibility_view(path, receipt) == successful
    with monkeypatch.context() as limited:
        limited.setattr(view, budget, observed - 1)
        limited.setattr(view, "inspect_docx", lambda *args: pytest.fail(
            "The binding processing limit must be checked before inspection"))
        with pytest.raises(view.CompatibilityError) as refused:
            view.rederive_compatibility_view(path, receipt)
        assert_budget(refused.value, label, observed, observed - 1, unit)

    assert view.rederive_compatibility_view(path, receipt) == successful
    assert successful.receipt_bytes == receipt and path.read_bytes() == original


def padded_source(tmp_path, *, parts=None, depth=None):
    path = source(tmp_path, divergent=True)
    with ZipFile(path) as archive:
        members = {info.filename: archive.read(info) for info in archive.infolist()}
    if parts is not None:
        assert len(members) < parts
        for index in range(parts - len(members)):
            members[f"custom/synthetic-padding-{index:04}.bin"] = b"x"
    if depth is not None:
        members["custom/synthetic-depth.xml"] = b"<n>" * depth + b"x" + b"</n>" * depth
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        for name, raw in members.items():
            archive.writestr(name, raw)
    return path


@pytest.mark.parametrize("parts", (512, 513))
def test_default_part_boundary_is_distinct_from_expanded_bytes(tmp_path, monkeypatch, parts):
    path = padded_source(tmp_path, parts=parts)
    original = path.read_bytes()
    with ZipFile(path) as archive:
        assert len(archive.infolist()) == parts
        expanded = sum(info.file_size for info in archive.infolist())
    # Under 1 MiB expanded: this is specifically the default part-count limit,
    # not a ZIP/source/expanded-byte limit or an artificially lowered part cap.
    assert expanded < 1024 * 1024 < view.MAX_VIEW_EXPANDED_BYTES
    if parts == 512:
        accepted = view.rederive_compatibility_view(path)
        assert view.rederive_compatibility_view(path, accepted.receipt_bytes) == accepted
    else:
        monkeypatch.setattr(view, "inspect_docx", lambda *args: pytest.fail(
            "An excessive package part count must precede inspection"))
        with pytest.raises(view.CompatibilityError) as refused:
            view.rederive_compatibility_view(path)
        assert "package expansion budget" not in str(refused.value)
        assert_budget(refused.value, "capability package part budget", 513, 512, "parts")
    assert path.read_bytes() == original


@pytest.mark.parametrize("depth", (64, 65))
def test_default_xml_depth_boundary_is_distinct_from_node_count(tmp_path, monkeypatch, depth):
    path = padded_source(tmp_path, depth=depth)
    original = path.read_bytes()
    assert measurements(original)["MAX_VIEW_XML_NODES"] < view.MAX_VIEW_XML_NODES
    if depth == 64:
        accepted = view.rederive_compatibility_view(path)
        assert view.rederive_compatibility_view(path, accepted.receipt_bytes) == accepted
    else:
        monkeypatch.setattr(view, "inspect_docx", lambda *args: pytest.fail(
            "Excessive XML depth must precede inspection"))
        with pytest.raises(view.CompatibilityError) as refused:
            view.rederive_compatibility_view(path)
        assert "XML complexity budget" not in str(refused.value)
        assert_budget(refused.value, "capability XML depth budget", 65, 64, "levels")
    assert path.read_bytes() == original


def test_bytes_api_reports_source_size_and_accepts_the_exact_limit(tmp_path, monkeypatch):
    path = source(tmp_path, divergent=True)
    original = path.read_bytes()
    successful = view.derive_compatibility_view(original)
    with monkeypatch.context() as exact:
        exact.setattr(view, "MAX_VIEW_SOURCE_BYTES", len(original))
        assert view.derive_compatibility_view(original) == successful
    with monkeypatch.context() as limited:
        limited.setattr(view, "MAX_VIEW_SOURCE_BYTES", len(original) - 1)
        limited.setattr(view, "inspect_docx", lambda *args: pytest.fail(
            "An excessive source size must precede inspection"))
        with pytest.raises(view.CompatibilityError) as refused:
            view.derive_compatibility_view(original)
        assert_budget(refused.value, "source byte budget", len(original), len(original) - 1)
    assert path.read_bytes() == original
    assert view.derive_compatibility_view(original) == successful


def test_growth_after_stat_reports_the_bounded_read_and_preserves_retry(tmp_path, monkeypatch):
    path = source(tmp_path, divergent=True)
    original = path.read_bytes()
    successful = view.rederive_compatibility_view(path)
    opens, reads = [], []
    original_open = Path.open

    class GrowingRead(BytesIO):
        def read(self, size=-1):
            reads.append(size)
            assert size == len(original) + 1
            return super().read(size)

    def opened(candidate, mode="r", *args, **kwargs):
        if candidate == path and mode == "rb":
            opens.append(mode)
            return GrowingRead(original + b"synthetic growth after stat")
        return original_open(candidate, mode, *args, **kwargs)

    with monkeypatch.context() as limited:
        limited.setattr(view, "MAX_VIEW_SOURCE_BYTES", len(original))
        limited.setattr(Path, "open", opened)
        limited.setattr(view, "inspect_docx", lambda *args: pytest.fail(
            "An overrun in the bounded source read must precede inspection"))
        with pytest.raises(view.CompatibilityError) as refused:
            view.rederive_compatibility_view(path, successful.receipt_bytes)
        assert_budget(refused.value, "source byte budget", len(original) + 1, len(original))
    assert opens == ["rb"] and reads == [len(original) + 1]
    assert path.read_bytes() == original
    assert view.rederive_compatibility_view(path, successful.receipt_bytes) == successful


def test_wrong_input_type_and_stale_receipt_remain_nonbudget_refusals(tmp_path):
    path = source(tmp_path, divergent=True)
    original = path.read_bytes()
    accepted = view.rederive_compatibility_view(path)
    for unsupported in (bytearray(original), None):
        with pytest.raises(view.CompatibilityError, match="source byte budget/type") as refused:
            view.derive_compatibility_view(unsupported)
        assert getattr(refused.value, "budget", None) is None
    with pytest.raises(view.CompatibilityError, match="stale or tampered source-view receipt") as refused:
        view.rederive_compatibility_view(path, b"{}")
    assert getattr(refused.value, "budget", None) is None
    assert path.read_bytes() == original
    assert view.rederive_compatibility_view(path, accepted.receipt_bytes) == accepted
