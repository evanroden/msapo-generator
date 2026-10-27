"""Byte labels and the native upload ceiling must never round an exact cap down."""
import pytest

from app.monthly_report_upload_limits import (
    MIB, byte_limit_label, docx_parser_help, docx_size_error, uploader_limit_mib,
)


@pytest.mark.parametrize("size,label,ceiling", [
    (1, "1 byte", 1),
    (1024, "1 KiB", 1),
    (MIB - 1, "1,048,575 bytes", 1),
    (MIB, "1 MiB", 1),
    (MIB + 1, "1,048,577 bytes", 2),
    (30 * MIB, "30 MiB", 30),
    (128 * MIB, "128 MiB", 128),
    (512 * MIB, "512 MiB", 512),
])
def test_exact_label_and_native_ceiling(size, label, ceiling):
    assert byte_limit_label(size) == label
    assert uploader_limit_mib(size) == ceiling
    assert (ceiling - 1) * MIB < size <= ceiling * MIB
    assert label in docx_size_error(size)
    assert "keep the original unchanged" in docx_size_error(size)


@pytest.mark.parametrize("value", [0, -1, True, False, 1.5, "128"])
def test_invalid_configuration_is_not_silently_coerced(value):
    with pytest.raises(ValueError):
        byte_limit_label(value)
    with pytest.raises(ValueError):
        uploader_limit_mib(value)


def test_expanded_media_and_xml_budgets_remain_distinct():
    text = docx_parser_help(expanded=256*MIB, member=64*MIB,
                            xml_part=32*MIB, xml_total=64*MIB, images=60*MIB)
    assert "256 MiB expanded DOCX" in text
    assert "64 MiB per embedded file" in text
    assert "32 MiB per XML part and 64 MiB total XML" in text
    assert "Selected prepared images have a 60 MiB budget" in text
    assert "below the upload limit can still exceed these limits" in text
    assert "keep the original unchanged" in text


def test_parser_help_uses_supplied_limits_not_embedded_policy_numbers():
    text = docx_parser_help(expanded=7*MIB, member=3*MIB,
                            xml_part=MIB, xml_total=2*MIB, images=4*MIB)
    for value in ("7 MiB", "3 MiB", "1 MiB", "2 MiB", "4 MiB"):
        assert value in text
    assert "256" not in text and "128" not in text
