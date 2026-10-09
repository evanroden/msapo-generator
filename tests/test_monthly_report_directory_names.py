"""Bound ElementTree's interned names as well as the streamed XML node count."""

from io import BytesIO
import tracemalloc
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from app import monthly_report_directory as directory


def workbook_with_parts(parts):
    base = {
        "[Content_Types].xml": "<Types/>",
        "xl/workbook.xml": (
            f'<workbook xmlns="{directory.S[1:-1]}" xmlns:r="{directory.R[1:-1]}">'
            '<sheets><sheet name="Synthetic" r:id="r1"/></sheets></workbook>'
        ),
        "xl/_rels/workbook.xml.rels": (
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="r1" Type="http://schemas.openxmlformats.org/officeDocument/'
            '2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>'
        ),
        "xl/worksheets/sheet1.xml": f'<worksheet xmlns="{directory.S[1:-1]}"/>',
    }
    stream = BytesIO()
    with ZipFile(stream, "w", ZIP_DEFLATED) as archive:
        for name, value in (base | parts).items():
            archive.writestr(name, value)
    return stream.getvalue()


@pytest.mark.parametrize("part,root", [
    ("xl/worksheets/sheet1.xml", "worksheet"),
    ("xl/sharedStrings.xml", "sst"),
    ("xl/workbook.xml", "workbook"),
    ("xl/_rels/workbook.xml.rels", "Relationships"),
])
def test_unique_ignored_names_reject_small_zip_before_parser_cache_grows(part, root):
    xml = f'<{root} xmlns="{directory.S[1:-1]}">' + "".join(f"<n{n}/>" for n in range(5000)) + f"</{root}>"
    raw = workbook_with_parts({part: xml})
    assert len(raw) < 16_000
    tracemalloc.start()
    try:
        with pytest.raises(ValueError, match="XML names exceed the safe parsing budget"):
            directory.inspect_workbook(raw)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 2 * 1024 * 1024


def test_unique_attribute_names_share_the_same_budget():
    xml = '<worksheet>' + "".join(f'<ignored a{n}=""/>' for n in range(600)) + '</worksheet>'
    with pytest.raises(ValueError, match="XML names exceed the safe parsing budget"):
        directory.inspect_workbook(workbook_with_parts({"xl/worksheets/sheet1.xml": xml}))


@pytest.mark.parametrize("attribute", [False, True])
def test_expanded_namespace_name_bytes_are_bounded(attribute):
    namespace = "urn:synthetic:" + "x" * 4000
    children = "".join(f'<ignored ns:n{n}=""/>' if attribute else f'<ns:n{n}/>' for n in range(40))
    xml = f'<worksheet xmlns:ns="{namespace}">{children}</worksheet>'
    with pytest.raises(ValueError, match="XML names exceed the safe parsing budget"):
        directory.inspect_workbook(workbook_with_parts({"xl/worksheets/sheet1.xml": xml}))


def test_namespace_rejects_before_many_attribute_names_are_expanded():
    namespace = "urn:synthetic:" + "x" * 100_000
    attributes = " ".join(f'ns:n{n}=""' for n in range(63))
    raw = workbook_with_parts({
        "xl/worksheets/sheet1.xml": f'<worksheet xmlns:ns="{namespace}" {attributes}/>',
    })
    assert len(raw) < 2000
    tracemalloc.start()
    try:
        with pytest.raises(ValueError, match="XML names exceed the safe parsing budget"):
            directory.inspect_workbook(raw)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 2 * 1024 * 1024


def test_oversized_start_tag_rejects_before_attribute_map_is_built():
    attributes = " ".join(f'a{n}=""' for n in range(25000))
    raw = workbook_with_parts({"xl/worksheets/sheet1.xml": f'<worksheet {attributes}/>'})
    tracemalloc.start()
    try:
        with pytest.raises(ValueError, match="XML token exceeds the safe parsing budget"):
            directory.inspect_workbook(raw)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 2 * 1024 * 1024


def test_name_budget_is_global_across_workbook_parts():
    # Each part separately has fewer than 512 names; their combined vocabulary
    # must still be rejected instead of restarting the allowance for each parser.
    strings = '<sst>' + "".join(f'<s{n}/>' for n in range(300)) + '</sst>'
    sheet = '<worksheet>' + "".join(f'<w{n}/>' for n in range(300)) + '</worksheet>'
    with pytest.raises(ValueError, match="XML names exceed the safe parsing budget"):
        directory.inspect_workbook(workbook_with_parts({
            "xl/sharedStrings.xml": strings, "xl/worksheets/sheet1.xml": sheet,
        }))


def test_repeated_names_do_not_spend_the_vocabulary_allowance():
    xml = '<worksheet>' + '<ignored same="value"/>' * 2000 + '</worksheet>'
    assert len(directory.inspect_workbook(workbook_with_parts({"xl/worksheets/sheet1.xml": xml})).sheets) == 1
