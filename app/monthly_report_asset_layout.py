"""Read-only layout intent for explicitly mapped current PDF source pages.

This is not a consent mechanism. Missing or ambiguous evidence retains the
ordinary photo layout; no filename, caption or aspect-ratio heuristics apply.
The existing prepare_pages map supplies layout intent, not a new independent
pixel-to-PDF proof. Current content-addressed asset loaders still verify bytes;
all source selection, review and generation gates remain separate.
"""
from dataclasses import replace
import re


def document_page_indexes(block, sources):
    if block.key != 'improvements':
        return frozenset()
    from app.monthly_report_asset_instances import valid_instances
    from app.monthly_report_asset_review import current_source_page_review_matches
    source_ids = [source.id for source in sources]
    # Exact occurrence records say which copy of equal bytes is the source
    # page. Without them, equal bytes cannot establish intent.
    occurrences = block.asset_instances if valid_instances(block) else None
    mapped = {}
    for asset, references in block.asset_provenance:
        if asset in mapped:
            return frozenset()  # Duplicate map entries cannot establish intent.
        mapped[asset] = references
    result = set()
    for index, asset in enumerate(block.asset_hashes):
        if ((occurrences is None and block.asset_hashes.count(asset) != 1)
                or not re.fullmatch(r'[0-9a-f]{64}\.(?:png|jpg)', asset)):
            continue
        references = occurrences[index].references if occurrences else mapped.get(asset, ())
        plain = [ref for ref in references if not ref.startswith('asset-source-context:v1:')]
        if len(plain) != 1 or plain[0] not in block.references:
            continue
        parts = plain[0].split(':')
        if len(parts) != 3 or not parts[1].isdigit() or source_ids.count(parts[0]) != 1:
            continue
        source = next(source for source in sources if source.id == parts[0])
        number = int(parts[1])
        if not (source.suffix == '.pdf' and 1 <= number <= len(source.page_texts)
                and number in source.selected_pages):
            continue
        # Existing per-asset approval binds the exact asset, caption and current
        # page-context digest. A bare editable marker never supplies authority.
        refreshed_review = current_source_page_review_matches(block, index, source, number)
        if parts[2] == source.fingerprint or refreshed_review:
            result.add(index)
    return frozenset(result)


def picture_runs(block, sources):
    """Original-order runs: individual documents, bounded ordinary photo grids."""
    documents = document_page_indexes(block, sources)
    if type(block.photos_per_page) is not int or not 1 <= block.photos_per_page <= 6:
        raise ValueError('Choose between 1 and 6 photos per page.')
    pending = []
    for index in range(len(block.asset_hashes)):
        if index in documents:
            if pending:
                yield False, tuple(pending)
                pending = []
            yield True, (index,)
        else:
            pending.append(index)
            if len(pending) == block.photos_per_page:
                yield False, tuple(pending)
                pending = []
    if pending:
        yield False, tuple(pending)


def photo_run(block, indexes):
    return replace(block, asset_hashes=tuple(block.asset_hashes[i] for i in indexes),
                   asset_captions=tuple(block.asset_captions[i] if i < len(block.asset_captions) else ''
                                        for i in indexes))


def photo_preview_references(draft):
    documents = {block.asset_hashes[index] for block in draft.blocks
                 for index in document_page_indexes(block, draft.sources)}
    photos = {asset for block in draft.blocks if block.key in ('cover_photo', 'improvements')
              for asset in block.asset_hashes}
    # One byte object can serve multiple occurrences. Its document occurrence
    # requires line-art fidelity even when another occurrence is a photograph.
    return photos - documents


def document_caption_problems(block, sources):
    """Bound new standalone captions to three 10pt lines in a 5in safe width."""
    from app.monthly_report_visuals import wrapped, font, _measure
    draw, face = _measure(), font(28)  # 10pt at the existing 200dpi layout scale.
    return tuple(index for index in document_page_indexes(block, sources)
                 if index < len(block.asset_captions)
                 and sum(max(1, len(wrapped(line, face, 1000, draw)))
                         for line in block.asset_captions[index].split('\n')) > 3)


def style_document_caption(paragraph):
    from docx.shared import Pt
    paragraph.paragraph_format.space_before = Pt(0)
    paragraph.paragraph_format.space_after = Pt(0)
    paragraph.paragraph_format.line_spacing = 1
    paragraph.paragraph_format.left_indent = Pt(0)
    paragraph.paragraph_format.right_indent = Pt(0)
    paragraph.paragraph_format.first_line_indent = Pt(0)
    paragraph.paragraph_format.keep_with_next = False
    paragraph.paragraph_format.keep_together = True
    paragraph.paragraph_format.page_break_before = False
    for run in paragraph.runs:
        run.font.name = 'DejaVu Sans'
        run.font.size = Pt(10)
        run.font.bold = False
        run.font.italic = False
