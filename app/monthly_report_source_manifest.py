"""Read-only, source-to-report completeness accounting for retained originals.

This is a *manifest*, not an import approval or an export gate. A page can
contain native text and an independent picture: both are observable elements.
Each physical row and each source notice has its own occurrence identity. A
missing cached extraction never masquerades as zero tables.
"""
from collections import Counter, defaultdict
from dataclasses import dataclass, replace

from app import monthly_report_sources as sources
from app.monthly_report_content_policy import page_fingerprint, page_status, page_allowed
from app.monthly_report_model import used_block_keys
from app.monthly_report_source_readiness import (
    _INFORMATIONAL_NOTICES, unresolved_reading_notices,
)
from app.monthly_report_source_scope import _covered_use, _source_id, source_uses


STATES = frozenset({"included", "extracted", "excluded", "blocked", "not_relevant", "unreadable"})
ACTIONABLE = frozenset({"included", "blocked", "unreadable"})


@dataclass(frozen=True)
class ManifestItem:
    source_id: str
    source_hash: str
    key: str
    kind: str
    page: int | None
    section: str
    status: str
    reason: str

    def __post_init__(self):
        if self.status not in STATES:
            raise ValueError("Unknown coverage state.")


@dataclass(frozen=True)
class SourceManifest:
    source_id: str
    source_hash: str
    source_revision: str
    filename: str
    report_period: str
    items: tuple[ManifestItem, ...]

    @property
    def counts(self):
        return dict(Counter(item.status for item in self.items))

    @property
    def pending(self):
        return tuple(item for item in self.items if item.status in ACTIONABLE)


def report_manifest(draft, contents):
    """Reconcile all current source identities, even when the cache is absent."""
    by_id = defaultdict(list)
    for content in contents:
        by_id[content.source.id].append(content)
    counts = Counter(source.id for source in draft.sources)
    seen, manifests = set(), []
    for source in draft.sources:
        if source.id in seen:
            continue
        seen.add(source.id)
        manifest = source_manifest(draft, source,
            by_id[source.id][0] if len(by_id[source.id]) == 1 else None)
        if counts[source.id] > 1:
            conflict = ManifestItem(source.id, source.sha256, "source:duplicate",
                "source", None, "", "blocked",
                "Multiple retained source records have the same identity.")
            manifest = replace(manifest, items=(*manifest.items, conflict))
        manifests.append(manifest)
    return tuple(manifests)


def report_manifest_counts(manifests):
    counts = Counter()
    sources_with_tasks = 0
    for manifest in manifests:
        counts.update(manifest.counts)
        sources_with_tasks += bool(manifest.pending)
    return {"sources": len(manifests), "sources_with_tasks": sources_with_tasks,
            "items": sum(counts.values()),
            **{name: counts[name] for name in sorted(STATES)}}


def _accepted_uses(draft, source):
    """Proof is current and item-specific, not a broad source reference."""
    result = []
    blocks = {block.key: block for block in draft.blocks}
    for use in source_uses(draft, source.id):
        if use[0] not in {"text", "rows", "organization", "follow_up"}:
            continue
        if _covered_use(use, source, draft.profile, draft.period, sources=draft.sources):
            result.append(use)
            continue
        block = blocks.get(use[1])
        if use[0] != "text" or block is None or not block.ai_written or not block.reviewed:
            continue
        from app.monthly_report_ai import ai_references, evidence_fingerprint
        # AI's evidence fingerprint binds source revisions but not the report
        # period. Without a period-bound contribution receipt above, a
        # previously reviewed block cannot approve a different report month.
        from datetime import date
        try:
            service_day = date.fromisoformat(source.service_date)
        except (TypeError, ValueError):
            continue
        if not draft.period.start <= service_day <= draft.period.end:
            continue
        refs = ai_references(block)
        if (any(_source_id(ref) == source.id for ref in refs)
                and block.ai_evidence_fingerprint
                and block.ai_evidence_fingerprint == evidence_fingerprint(draft.sources, refs)):
            result.append(use)
    return tuple(result)


def _reviewed_images(draft, source):
    """Index only current, unique, reviewed image occurrences in included blocks."""
    from app.monthly_report_asset_review import (
        asset_context, pending_asset_indexes, current_source_page_review_matches,
        _source_context_marker,
    )
    from app.monthly_report_page_controls import included_page_caption
    from app.monthly_report_section_uploads import page_identity
    from app.monthly_report_source_scope import reviewed_scope

    owners = defaultdict(list)
    keys = used_block_keys(draft)
    for block in draft.blocks:
        if block.key not in keys or block.source == "Omit" or not block.asset_hashes:
            continue
        pending = set(pending_asset_indexes(block, draft.sources))
        for index in range(len(block.asset_hashes)):
            context = asset_context(block, index)
            pairs = {pair for ref in context if (pair := page_identity(ref)) is not None}
            for identity in pairs:
                if identity[0] == source.id:
                    owners[identity[1]].append((block, index, context, pairs, index in pending))

    approved = {}
    for number, occurrences in owners.items():
        if len(occurrences) != 1 or not 1 <= number <= len(source.page_texts):
            continue
        block, index, context, pairs, pending = occurrences[0]
        if pending or pairs != {(source.id, number)} or number not in source.selected_pages:
            continue
        if not page_allowed(source, number, profile=draft.profile, destination=block.key):
            continue
        references = tuple(ref for ref in context if page_identity(ref) is not None)
        scoped = (reviewed_scope(source, draft.profile) is not None
                  and _source_context_marker(source, number) in context)
        if (set(references) != {sources.source_reference(source, number)}
                and not (scoped or current_source_page_review_matches(
                    block, index, source, number, profile=draft.profile))):
            continue
        if any(page_identity(ref) is None and not ref.startswith("asset-source-context:v1:")
               for ref in context):
            continue
        caption = block.asset_captions[index] if index < len(block.asset_captions) else ""
        if caption != included_page_caption(block, source, number):
            continue
        approved[number] = block.key
    return approved


def source_manifest(draft, source, content=None):
    """Audit one inspected original without changing source/report or disk state.

    'extracted' requires current acceptance proof, 'included' means visible
    evidence still awaiting placement/confirmation, and 'excluded' records a
    current human page decision or a specific client-output policy. A scan
    without readable text remains unreadable until its original image is
    actually reviewed and attached. This function never runs a paid reader.
    """
    items = []
    def add(key, kind, page, section, status, reason):
        items.append(ManifestItem(source.id, source.sha256, key, kind, page,
                                  section, status, reason))

    if source.id not in {item.id for item in draft.sources}:
        add("source:retired", "source", None, "", "blocked", "Source is no longer in this report.")
        return SourceManifest(source.id, source.sha256, source.fingerprint,
                              source.filename, draft.period.key, tuple(items))
    if (content is not None and (content.source.id != source.id
            or content.source.sha256 != source.sha256 or content.source.suffix != source.suffix)):
        add("source:replaced", "source", None, "", "blocked",
            "Cached extraction belongs to a different original; re-inspect the current file.")
        content = None
    if source.suffix not in sources.SUPPORTED:
        add("source:unsupported", "source", None, "", "blocked",
            "This file type is not supported for inspection.")
        return SourceManifest(source.id, source.sha256, source.fingerprint,
                              source.filename, draft.period.key, tuple(items))
    if content is None:
        add("source:unavailable", "source", None, "", "blocked",
            "Original extraction is unavailable; re-open the unchanged source.")
    elif content.source.page_texts != source.page_texts:
        add("source:stale-text", "source", None, "", "blocked",
            "Inspected text differs from current source details.")

    uses = source_uses(draft, source.id)
    accepted = (_accepted_uses(draft, source)
                if content is not None and content.source.page_texts == source.page_texts else ())
    sections = {spec.key: section.title for section in draft.sections for spec in section.blocks}
    approved_images = _reviewed_images(draft, source) if content is not None else {}
    exclusions = dict(source.client_page_exclusions)
    image_indexes = set(sources.image_numbers(content)) if content is not None else set()
    # A PDF may contain text and a picture on the same physical page. Avoid
    # claiming every text PDF page needs a duplicate image task; only selected
    # pages, unreadable pages and DOCX embedded images are image candidates.
    # In a PDF/image original the page entry already owns its rendered view;
    # counting it again as a photo would double-count a scan canary.
    images = image_indexes if source.suffix == ".docx" else set()

    def decision(number):
        status, reason = page_status(source.page_texts[number - 1],
                                     unreadable=number in source.needs_vision)
        excluded = exclusions.get(number)
        if excluded == page_fingerprint(source, number):
            return "excluded", "Deliberately excluded from this report (current page receipt)."
        if excluded:
            return "blocked", "Page exclusion belongs to an older source revision."
        if status in {"pricing", "legal", "signature"}:
            return "excluded", "Client-output policy exclusion: " + reason
        if status == "blank" and number not in images:
            return "not_relevant", "No parser-visible report content."
        return None, ""

    for number, text in enumerate(source.page_texts, 1):
        # An image-only DOCX item is a photo occurrence, not a second empty
        # paragraph. Keep a separate page only when native text also exists.
        if source.suffix == ".docx" and number in images and not text.strip():
            continue
        forced, reason = decision(number)
        if forced:
            add(f"page:{number}", "page", number, "", forced, reason)
            continue
        matching = next((use for use in accepted if use[0] == "text"
                         and isinstance(use[2], str) and text.strip()
                         and text.strip() in use[2]
                         and sources.source_reference(source, number) in use[3]), None)
        if matching:
            add(f"page:{number}", "page", number, sections.get(matching[1], matching[1]),
                "extracted", "Exact page text retained in a currently accepted report field.")
        elif number in source.needs_vision and number not in approved_images:
            add(f"page:{number}", "page", number, "", "unreadable",
                "Image or scan needs visual reading; upload acceptance is not evidence.")
        elif number in approved_images:
            add(f"page:{number}", "page", number,
                sections.get(approved_images[number], approved_images[number]), "extracted",
                "Current original page is reviewed and attached in the report.")
        elif number in source.selected_pages:
            add(f"page:{number}", "page", number, "", "blocked",
                "Selected original page is not a uniquely reviewed report attachment.")
        elif not uses and source.classification == "Reference only":
            add(f"page:{number}", "page", number, "", "included",
                "Reference-only classification does not prove this content is irrelevant.")
        else:
            add(f"page:{number}", "page", number, "", "included",
                "Readable original retained; no exact accepted full-page destination.")

    # Native DOCX image indexes are item identities, not invented Word pages.
    # For PDFs these are current selected/scan page candidates only.
    for number in sorted(images):
        if number < 1 or number > len(source.page_texts):
            add(f"photo:{number}", "photo", None, "", "blocked",
                "Original image item has no current page identity.")
            continue
        forced, reason = decision(number)
        if forced == "excluded":
            add(f"photo:{number}", "photo", number, "", forced, reason)
        elif number in approved_images:
            section = approved_images[number]
            add(f"photo:{number}", "photo", number, sections.get(section, section),
                "extracted", "Reviewed original image is attached once.")
        elif forced == "blocked":
            add(f"photo:{number}", "photo", number, "", forced, reason)
        elif number in source.needs_vision:
            add(f"photo:{number}", "photo", number, "", "unreadable",
                "Scanned or image-only content has not been reviewed and attached.")
        else:
            add(f"photo:{number}", "photo", number, "", "included",
                "Image retained for page/photo review; no current attached proof.")

    if content is not None:
        accepted_rows = Counter()
        row_sections = {}
        for use in accepted:
            if use[0] != "rows":
                continue
            for index in range(1, len(content.tables) + 1):
                if any(ref.startswith(f"{source.id}:{index}:") for ref in use[3]):
                    for row in use[2][1]:
                        identity = (index, tuple(row))
                        accepted_rows[identity] += 1
                        row_sections.setdefault(identity, use[1])
        for number, table in enumerate(content.tables, 1):
            # Cached/legacy malformed data is an explicit blocker, not a
            # zero-row success and never a source of accepted row claims.
            if (not table.columns or any(
                    len(row) != len(table.columns)
                    or any(not isinstance(cell, str) for cell in row)
                    for row in table.rows)):
                add(f"table:{number}:malformed", "table", number, "",
                    "blocked", "Extracted table has incompatible row widths or types.")
                continue
            row_states = []
            for index, row in enumerate(table.rows, 1):
                identity = (number, tuple(row))
                matched = accepted_rows[identity] > 0
                if matched:
                    accepted_rows[identity] -= 1
                state = "extracted" if matched else "included"
                section = row_sections.get(identity, "") if matched else ""
                add(f"table:{number}:row:{index}", "row", number,
                    sections.get(section, section), state,
                    "Exact accepted table-row occurrence." if matched else
                    "Parsed source row has no exact accepted editable destination.")
                row_states.append(state)
            if not table.rows:
                state = "not_relevant"
            elif all(value == "extracted" for value in row_states):
                state = "extracted"
            elif all(value == "not_relevant" for value in row_states):
                state = "not_relevant"
            else:
                state = "included"
            add(f"table:{number}", "table", number, "", state,
                f"Parsed table ({len(table.rows)} physical data rows); see its row occurrences.")
    elif source.suffix in {".csv", ".xlsx", ".docx"}:
        add("tables:unknown", "table", None, "", "blocked",
            "Cannot verify table count until the original extraction is available.")

    for index, fact in enumerate(source.facts, 1):
        match = next((use for use in accepted if use[0] == "text" and
                      isinstance(use[2], str) and fact.text.strip() and
                      fact.text.strip() in use[2] and
                      any(ref.startswith(f"{source.id}:{fact.page}:") for ref in use[3])), None)
        section = match[1] if match else ""
        add(f"fact:{index}:{fact.id}", "fact",
            fact.page if 1 <= fact.page <= len(source.page_texts) else None,
            sections.get(section, section), "extracted" if match else "included",
            "Exact cited fact in accepted text." if match else
            "Extracted fact has no exact accepted report destination.")

    remaining = Counter(unresolved_reading_notices(source))
    for index, notice in enumerate(source.notices, 1):
        if notice in _INFORMATIONAL_NOTICES:
            state, reason = "not_relevant", "Informational reader description."
        elif remaining[notice]:
            remaining[notice] -= 1
            state, reason = "blocked", "Unresolved original reader/drawing notice: " + notice[:180]
        else:
            state, reason = "excluded", "Current explicit source-page decision accounts for this notice."
        add(f"notice:{index}", "drawing_or_notice", None, "", state, reason)

    if not items:
        add("source:empty", "source", None, "", "blocked",
            "No inspectable source elements; verify the original.")
    return SourceManifest(source.id, source.sha256, source.fingerprint,
                          source.filename, draft.period.key, tuple(items))
