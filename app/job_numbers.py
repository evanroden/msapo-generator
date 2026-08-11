"""Verified Smartsheet JOB NUMBER options and account-scoped suggestions."""

from __future__ import annotations

import re
from collections.abc import Sequence


JOB_NUMBER_OPTIONS: tuple[str, ...] = (
    "ACU 69500001 - ES JOB CCJ",
    "ACU VI100043 - NEA",
    "ACU VI100044 - QMA - CFC O&M",
    "ACU VI100054 - ISDC",
    "ACU VI100055 - STARTUP",
    "ADVENTIST-695000002-ES JOB CCJ",
    "ADVENTIST-695400001-O&M",
    "BAPTIST KY-695000003-ES JOB CCJ",
    "BAPTIST KY-695400026-ESA",
    "BAPTIST KY-695400027-NESA",
    "BAPTIST KY-695400040-O&M STARTUP",
    "BAPTIST KY-695400041 ISDC",
    "BEACON-695000004-ES JOB CCJ",
    "BEACON-695400009-ISDC",
    "BEACON-695400019-O&M",
    "CFNI-VI100029-O&M",
    "CFNI-VI100052-ISDC",
    "Christus 695000013 - ES JOB CCJ",
    "Christus VI100025 - O&M",
    "Christus VI100048 - ISDC",
    "Clinton 695400004 - O&M",
    "Clinton 695400018 - ISDC",
    "CONWAY-695000015-ES JOB CCJ",
    "CONWAY-695000032-PRIMARY CARE",
    "CONWAY-VI100026-O&M",
    "CONWAY-VI100049-ISDC",
    "EAMC-695000016-ES JOB CCJ",
    "EAMC-VI100007-O&M MONTH MGMT",
    "EAMC-VI100008-O&M",
    "EJGH-695000007-ES JOB CCJ",
    "EJGH-VI100012-O&M",
    "HACKENSACK-695000018-ES JOB CCJ",
    "HACKENSACK-VI100031-O&M",
    "HAMPTON-695000017-ES JOB CCJ",
    "HAMPTON-VI100009-O&M",
    "HARTFORD-695400045-EA",
    "HARTFORD-695400046-NEA",
    "LSU NO-695000030-ES JOB CCJ",
    "LSU NO-VI100023-O&M",
    "MAURY-695000019-ES JOB CCJ",
    "MAURY-VI100027-O&M",
    "MCH 695400021 - O&M",
    "MCH 695400024 - STARTUP",
    "MCH 695400025 - ISDC",
    "MEM HEALTH IL-695400031-ESE",
    "MEM HEALTH IL-695400032-NESE",
    "MEM HEALTH IL-695400036-ES JOB CCJ",
    "MEM HEALTH IL-695400039-ISDC",
    "MFC-695000005-ES JOB CCJ",
    "MFC-VI100011-O&M",
    "Midland 695000020 - ES JOB CCJ",
    "Midland VI100006 - O&M",
    "NOVANT-695000021-ES JOB CCJ",
    "NOVANT-695400012-ESA",
    "NOVANT-695400013-NESA",
    "NOVANT-695400015-O&M STARTUP",
    "NOVANT-695400016-ISDC",
    "OCHSNER BAPTIST-695000022-ES JOB",
    "OCHSNER BAPTIST-VI100005-O&M",
    "OCHSNER BAPTIST-VI100021-ISDC",
    "OCHSNER GROVE-695000023-ES JOB CCJ",
    "OCHSNER GROVE-VI100004-O&M",
    "OCHSNER MAIN-695000024-ES JOB CCJ",
    "OCHSNER MAIN-VI100017-O&M",
    "OLOL-695000025-ES JOB CCJ",
    "OLOL-VI100003-O&M",
    "PECHE-695000011-ESJOB CCJ",
    "PECHE-VI100028-O&M",
    "Permian Basin 695400044 - O&M",
    "PIH-695400002-O&M",
    "RRH-695400022-O&M",
    "RRH-695400023-START UP",
    "RRH-695400030-ISDC",
    "RRH-695400034-ES JOB CCJ",
    "SHAW-695000027-ES JOB CCJ",
    "SHAW-VI100000-O&M",
    "TOURO/WOLDENBERG-695000006-ES/CCJ",
    "TOURO/WOLDENBERG-VI100014-O&M",
    "TULANE DCC-695000031",
    "TULANE EA- VI100018-O&M",
    "TULANE NEA-VI100020",
    "TULANE-695000028-ES JOB CCJ",
    "Unity 695000029 - CCJ",
    "Unity VI100036 - O&M",
    "Unity VI100056 - ISDC",
    "WJGH-695000008-ES JOB CCJ",
    "WJGH-VI100016-O&M",
)

RRH_JOB_NUMBERS: tuple[str, ...] = tuple(
    value for value in JOB_NUMBER_OPTIONS if value.startswith("RRH-")
)

# These three options belong to Unity Health System in Arkansas. They never
# describe Unity Hospital or Unity Specialty Hospital in Rochester, New York;
# those RRH sites use one of the RRH-prefixed options above.
ARKANSAS_UNITY_JOB_NUMBERS: tuple[str, ...] = tuple(
    value for value in JOB_NUMBER_OPTIONS if value.startswith("Unity ")
)

UNITY_DISAMBIGUATION_GUIDANCE = """\
UNITY DISAMBIGUATION — IMPORTANT:
- Smartsheet JOB NUMBER options beginning "Unity" belong to Unity Health
  System in Arkansas.
- Unity Hospital and Unity Specialty Hospital in the Rochester, New York area
  belong to the Rochester Regional Health (RRH) account and use RRH-prefixed
  job numbers.
- Vendor quotes often shorten the Rochester facility to just "Unity." Never
  classify a quote as the Arkansas account from that word alone. Use RRH,
  Rochester, New York, Long Pond Road, Genesee Street, ZIP code, and other
  address/account evidence. If the context remains ambiguous, leave the routing
  for the operator to confirm rather than selecting Arkansas Unity.
"""

_JOB_IDENTIFIER_RE = re.compile(r"\b(?:VI\d+|695\d+)\b", re.IGNORECASE)
_ACCOUNT_ALIASES = {
    "rochesterregionalhealth": "rrh",
    "rrh": "rrh",
    "unityhealthsystem": "unity",
    "memorialhealthillinois": "memhealthil",
}


def _normalized(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _account_label(option: str) -> str:
    match = _JOB_IDENTIFIER_RE.search(option)
    return option[: match.start()].strip(" -") if match else option.strip(" -")


def job_numbers_for_contract(contract: str) -> tuple[str, ...]:
    """Return likely options for one configured account, preserving all fallbacks.

    Exact/specific account labels are preferred. When an imported contract name
    has no recognizable catalog label, the complete verified list is returned
    so the operator is never forced into an invented free-text value.
    """
    contract_text = str(contract or "").strip()
    contract_normalized = _normalized(contract_text)
    target = _ACCOUNT_ALIASES.get(contract_normalized, contract_normalized)
    if target == "rrh":
        return RRH_JOB_NUMBERS

    first_word = _normalized(contract_text.split()[0]) if contract_text else ""
    matches: list[str] = []
    for option in JOB_NUMBER_OPTIONS:
        label = _account_label(option)
        normalized_label = _normalized(label)
        normalized_first = _normalized(label.split()[0]) if label else ""
        if (
            normalized_label == target
            or normalized_label.startswith(target)
            or target.startswith(normalized_label)
            or (
                len(first_word) >= 3
                and first_word == normalized_first
            )
        ):
            matches.append(option)
    return tuple(matches) or JOB_NUMBER_OPTIONS


def suggest_job_number(
    options: Sequence[str], quote_text: str
) -> str | None:
    """Suggest only an exact catalog option supported by a quoted job identifier."""
    source = str(quote_text or "")
    supported: list[str] = []
    for option in options:
        match = _JOB_IDENTIFIER_RE.search(option)
        if match and re.search(
            rf"(?<![A-Za-z0-9]){re.escape(match.group(0))}(?![A-Za-z0-9])",
            source,
            flags=re.IGNORECASE,
        ):
            supported.append(option)
    if len(supported) == 1:
        return supported[0]
    if len(options) == 1:
        return str(options[0])
    return None


def job_number_identifier(option: str | None) -> str | None:
    """Return the exact JDE job identifier embedded in a catalog option.

    The Smartsheet-facing catalog keeps its descriptive account label, while
    the reimbursement workbook accepts only the numeric/VI identifier in the
    ``Job or Service Center #`` column.  Keeping this extraction beside the
    verified catalog prevents a second, drifting list.
    """
    match = _JOB_IDENTIFIER_RE.search(str(option or ""))
    return match.group(0).upper() if match else None
