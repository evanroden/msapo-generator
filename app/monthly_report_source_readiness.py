"""Read-only summaries of actual included/accepted text and table tasks.

An uploaded file alone is not reviewed. Scope receipts are used only for the
accepted contribution they cover; original image-page decisions stay separate.
"""
from dataclasses import dataclass

from app.monthly_report_source_scope import (
    USE_PREFIX, _covered_use, _decode, _source_id, source_uses,
)

# These exact route disclosures describe normal extraction, not a failed or
# pending task. Keep them on the original source and in its details. Unknown,
# malformed-content, missing-artwork and unsafe-object notices remain visible
# correction work; never classify them by a broad substring.
_INFORMATIONAL_NOTICES = frozenset({
    "Workbook values use stored formula results; formulas are never executed. Missing cached results remain blank.",
    "DOCX selections are extracted items, not Word page numbers.",
})


def unresolved_reading_notices(source):
    return tuple(notice for notice in source.notices if notice not in _INFORMATIONAL_NOTICES)


@dataclass(frozen=True)
class SourceContentReadiness:
    included: bool = False
    accepted: bool = False
    summary: str = "Not included"
    problem: str = ""
    destinations: tuple[str, ...] = ()


def content_readiness(draft, source):
    uses = tuple(use for use in source_uses(draft, source.id)
                 if use[0] in {"text", "rows", "follow_up", "organization"})
    if not uses:
        return SourceContentReadiness()
    destinations = tuple(dict.fromkeys(use[1] for use in uses))
    titles = dict((spec.key, section.title) for section in draft.sections for spec in section.blocks)
    locations = ", ".join(dict.fromkeys(titles.get(key, key.replace("_", " ")) for key in destinations))
    blocks = {block.key: block for block in draft.blocks}

    def current_review(use):
        block = blocks.get(use[1])
        if use[0] != "text" or block is None or not block.ai_written or not block.reviewed:
            return False
        from app.monthly_report_ai import ai_references, evidence_fingerprint
        references = ai_references(block)
        return bool(any(_source_id(ref) == source.id for ref in references)
                    and block.ai_evidence_fingerprint and block.ai_evidence_fingerprint ==
                    evidence_fingerprint(draft.sources, references))

    covered = tuple(_covered_use(use, source, draft.profile, draft.period, sources=draft.sources) for use in uses)
    reviewed = tuple(current_review(use) for use in uses)
    accepted = all(a or b for a, b in zip(covered, reviewed))
    kinds = {use[0] for use in uses}
    label = ("Totals accepted" if all(covered) and kinds == {"text"} else
             "Tables accepted" if all(covered) and kinds == {"rows"} else
             "Content reviewed" if accepted else "Included content")
    problem = ""
    if not accepted:
        # A changed receipt must not become a generic ready label merely
        # because some text still cites the file. Keep this source's precise
        # acceptance task actionable; unrelated sources remain unchanged.
        own_receipt = any(_source_id(_decode(ref[len(USE_PREFIX):]).get("reference")) == source.id
            for use in uses for ref in use[3] if ref.startswith(USE_PREFIX))
        if own_receipt:
            problem = "Review the changed totals or mapped rows."
        elif any(blocks.get(use[1]) is not None and blocks[use[1]].ai_written
                 and not current_review(use) for use in uses):
            problem = "Review the current suggested wording and its evidence."
    return SourceContentReadiness(True, accepted, label + " · " + locations,
                                  problem, destinations)
