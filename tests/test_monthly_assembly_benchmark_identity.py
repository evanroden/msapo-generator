"""Synthetic ZIP metadata is not native package content identity."""
from io import BytesIO
from zipfile import ZipFile, ZipInfo
import warnings

import pytest

from scripts.qa_monthly_preview_assembly_latency import package_content_sha256


def archive(parts, year=2020):
    buffer = BytesIO()
    with ZipFile(buffer, 'w') as package:
        for name, content in parts:
            package.writestr(ZipInfo(name, (year, 1, 1, 0, 0, 0)), content)
    return buffer.getvalue()


def test_timestamp_and_member_order_do_not_change_exact_package_content_identity():
    parts = [('word/document.xml', b'<document/>'), ('word/media/synthetic.png', b'pixels')]
    first = archive(parts)
    later = archive(list(reversed(parts)), 2026)
    assert first != later
    assert package_content_sha256(first) == package_content_sha256(later)


@pytest.mark.parametrize('changed', [
    [('word/document.xml', b'<changed/>'), ('word/media/synthetic.png', b'pixels')],
    [('word/document.xml', b'<document/>'), ('word/media/renamed.png', b'pixels')],
    [('word/document.xml', b'<document/>')],
    [('word/document.xml', b'<document/>'), ('word/media/synthetic.png', b'pixels'), ('extra', b'')],
])
def test_any_member_content_name_addition_or_removal_changes_identity(changed):
    before = archive([('word/document.xml', b'<document/>'), ('word/media/synthetic.png', b'pixels')])
    assert package_content_sha256(before) != package_content_sha256(archive(changed))


def test_duplicate_member_names_are_rejected_even_with_identical_bytes():
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', UserWarning)
        raw = archive([('word/document.xml', b'x'), ('word/document.xml', b'x')])
    with pytest.raises(ValueError, match='Duplicate package member'):
        package_content_sha256(raw)


def test_unframed_name_content_boundary_cannot_collide():
    assert package_content_sha256(archive([('a', b'bc')])) != package_content_sha256(archive([('ab', b'c')]))
