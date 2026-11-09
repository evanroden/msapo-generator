"""Exact byte-limit wording; native uploader limits are only an admission ceiling."""

MIB = 1024 * 1024


def byte_limit_label(limit_bytes: int) -> str:
    """Keep displayed limits exact, including non-MiB limits used in tests."""
    if type(limit_bytes) is not int or limit_bytes <= 0:
        raise ValueError("An upload limit must be a positive integer number of bytes.")
    if limit_bytes % MIB == 0:
        return f"{limit_bytes // MIB:,} MiB"
    if limit_bytes % 1024 == 0:
        return f"{limit_bytes // 1024:,} KiB"
    return f"{limit_bytes:,} byte" + ("s" if limit_bytes != 1 else "")


def uploader_limit_mib(limit_bytes: int) -> int:
    """Round up for the native whole-MiB widget; keep exact server-side checks."""
    byte_limit_label(limit_bytes)  # Reject invalid configuration consistently.
    return (limit_bytes + MIB - 1) // MIB


def docx_size_error(limit_bytes: int) -> str:
    return (f"DOCX exceeds the {byte_limit_label(limit_bytes)} import limit. "
            "Choose a smaller copy for import; keep the original unchanged.")


def docx_parser_help(*, expanded: int, member: int, xml_part: int,
                     xml_total: int, images: int) -> str:
    """Describe parser budgets separately from the uploaded ZIP's byte size."""
    return (
        f"Separate parsing limits: {byte_limit_label(expanded)} expanded DOCX; "
        f"{byte_limit_label(member)} per embedded file; "
        f"{byte_limit_label(xml_part)} per XML part and "
        f"{byte_limit_label(xml_total)} total XML. "
        f"Selected prepared images have a {byte_limit_label(images)} budget. "
        "A file below the upload limit can still exceed these limits. "
        "Use a smaller import copy or fewer selected images; keep the original unchanged."
    )


def source_size_error(suffix: str, limit_bytes: int) -> str:
    """Name the actual type's limit rather than the largest chooser ceiling."""
    return (f"This {suffix.lstrip('.').upper()} file exceeds the "
            f"{byte_limit_label(limit_bytes)} upload limit. "
            "Choose a smaller copy; keep the original unchanged.")
