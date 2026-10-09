"""Read-only, human-readable comparison before accepting a newer saved revision."""

from dataclasses import dataclass, replace

import streamlit as st

from app.monthly_report_asset_review import normalize_asset_reviews, pending_asset_indexes
from app.monthly_report_sections import readable_label


@dataclass(frozen=True)
class Comparison:
    title: str
    saved: str
    working: str
    saved_images: tuple[str, ...] = ()
    working_images: tuple[str, ...] = ()


def _lines(values):
    return "\n".join(str(v) for v in values) or "None"


def _sites(profile):
    return _lines(f.title + (" (also called " + ", ".join(f.aliases) + ")" if f.aliases else "")
                  for f in profile.facilities)


def _table(columns, rows):
    titles = [getattr(c, "title", c) for c in columns]
    return _lines("Row " + str(n + 1) + ": " + "; ".join(
        str(titles[i] if i < len(titles) else f"Column {i + 1}") + ": " + str(value)
        for i, value in enumerate(row)) for n, row in enumerate(rows))


def _block_summary(block, spec, draft):
    if block is None:
        return "Not present"
    values = ["Left out of the report" if block.source == "Omit" else "Included content"]
    if spec and spec.columns:
        values.append("Table headings: " + ", ".join(c.title for c in spec.columns))
    if block.text:
        values.append(block.text)
    if block.rows:
        values.append(_table(spec.columns if spec else (), block.rows))
    for n, table in enumerate(block.extra_tables):
        values.append(f"Table {n + 1}: " + ", ".join(table.columns))
        values.append(_table(table.columns, table.rows))
    if block.org_nodes:
        people = {p.key: p.name or p.role or "Unnamed person" for p in block.org_nodes}
        values.extend((p.name or "Name not entered") + " — " + (p.role or "Role not entered")
                      + ("; reports to " + people.get(p.reports_to, "a person no longer listed") if p.reports_to else "")
                      + ("; team: " + p.team if p.team else "") for p in block.org_nodes)
    if block.asset_hashes:
        values.append(f"{len(block.asset_hashes)} pictures/pages; {block.photos_per_page} per page")
        values.extend(f"Caption {n + 1}: {caption}" for n, caption in enumerate(block.asset_captions) if caption)
    if block.ai_paragraphs:
        values.extend(p.text for p in block.ai_paragraphs if p.text != block.text)
    if block.ai_written:
        values.append("Suggested wording reviewed" if block.reviewed else "Suggested wording needs review")
    if block.asset_hashes:
        pending = len(pending_asset_indexes(block, draft.sources))
        values.append("Pictures/pages reviewed" if not pending else f"{pending} of {len(block.asset_hashes)} pictures/pages need review")
    if block.references:
        values.append("Linked evidence: " + _lines(s.filename for s in draft.sources
                       if any(ref == s.id or ref.startswith(s.id + ":") for ref in block.references)))
    return "\n\n".join(values)


def _followups(items):
    return _lines(("Included" if item.included else "Left out") + " · "
                  + item.category.replace("_", " ").capitalize() + " · " + item.status.capitalize()
                  + "\n" + item.text + ("\nUpdate: " + item.update if item.update else "")
                  + ("\nEvidence: " + item.evidence_note if item.evidence_note else "")
                  + ("\nCarried from: " + item.carried_from if item.carried_from else "")
                  + ("\nReview recorded" if item.reviewed_fingerprint else "\nNeeds review")
                  + f"\nLinked evidence: {len(item.references)} reference(s)"
                  for item in items)


def compare_drafts(working, saved):
    """Return visible differences without exposing hashes, object IDs or JSON."""
    changes = []

    def add(title, before, after, *, force=False, saved_images=(), working_images=()):
        if before != after or force:
            changes.append(Comparison(title, str(before), str(after), saved_images, working_images))

    add("Contract", saved.profile.contract, working.profile.contract)
    add("Report name", saved.profile.title, working.profile.title)
    scope = {"individual": "One site", "multi_site": "Several sites in one report", "regional": "Regional report"}
    add("Report coverage", scope[saved.profile.scope_type], scope[working.profile.scope_type])
    add("Sites and alternate names", _sites(saved.profile), _sites(working.profile),
        force=saved.profile.facilities != working.profile.facilities)
    add("Reporting month", saved.period.label, working.period.label)
    add("Prepared by", saved.prepared_by, working.prepared_by)
    add("Address/footer", saved.address_line, working.address_line)
    add("Known equipment tags", _lines(saved.profile.asset_tags), _lines(working.profile.asset_tags))
    add("Report section order", _lines(s.title for s in saved.sections), _lines(s.title for s in working.sections))
    before_sections = {s.key: s for s in saved.sections}
    after_sections = {s.key: s for s in working.sections}
    for key in dict.fromkeys((*before_sections, *after_sections)):
        before, after = before_sections.get(key), after_sections.get(key)
        label = (after or before).title
        def section_status(section):
            if section is None:
                return "Not present"
            return ("Included" if section.included else "Left out") + (" · Appendix" if section.appendix else "")
        add(label + " — inclusion", section_status(before), section_status(after))
        if before and after:
            add(label + " — content order", _lines(readable_label(b.key) for b in before.blocks),
                _lines(readable_label(b.key) for b in after.blocks))
            if before.divider_asset != after.divider_asset:
                add(label + " — divider photograph", "Saved photograph" if before.divider_asset else "No photograph",
                    "Your photograph" if after.divider_asset else "No photograph", force=True,
                    saved_images=(before.divider_asset,) if before.divider_asset else (),
                    working_images=(after.divider_asset,) if after.divider_asset else ())
    saved_specs = {b.key: b for s in saved.sections for b in s.blocks}
    working_specs = {b.key: b for s in working.sections for b in s.blocks}
    before_blocks = {b.key: b for b in saved.blocks}
    after_blocks = {b.key: b for b in working.blocks}
    for key in dict.fromkeys((*before_blocks, *after_blocks)):
        before, after = before_blocks.get(key), after_blocks.get(key)
        comparable_before = replace(normalize_asset_reviews(before), client_reviewed_fingerprint="") if before else None
        comparable_after = replace(normalize_asset_reviews(after), client_reviewed_fingerprint="") if after else None
        if comparable_before == comparable_after and saved_specs.get(key) == working_specs.get(key):
            continue
        before_text = _block_summary(before, saved_specs.get(key), saved)
        after_text = _block_summary(after, working_specs.get(key), working)
        if before_text == after_text:
            before_text += "\n\nThe pictures, table headings, linked evidence or review details differ."
            after_text += "\n\nThe pictures, table headings, linked evidence or review details differ."
        add(readable_label(key), before_text, after_text, force=True,
            saved_images=before.asset_hashes if before else (), working_images=after.asset_hashes if after else ())
    if saved.follow_ups != working.follow_ups:
        before, after = _followups(saved.follow_ups), _followups(working.follow_ups)
        if before == after:
            before += "\n\nThe linked evidence or review record differs. Recheck the open issue against its sources."
            after += "\n\nThe linked evidence or review record differs. Recheck the open issue against its sources."
        add("Open issues and proposals", before, after, force=True)
    if saved.sources != working.sources:
        def source_summary(sources):
            return _lines(s.filename + " · " + s.classification + "\nSelected pages: "
                          + (", ".join(str(p) for p in s.selected_pages) or "None")
                          + "\nVendor: " + (s.vendor or "Not entered")
                          + "\nService date: " + (s.service_date or "Not entered")
                          + "\nFacility: " + (s.facility or "Not entered")
                          + ("\nWork: " + s.actions if s.actions else "")
                          + ("\nFindings: " + s.findings if s.findings else "")
                          + ("\nRecommendations: " + s.recommendations if s.recommendations else "")
                          + ("\nFollow-ups: " + s.follow_ups if s.follow_ups else "") for s in sources)
        before, after = source_summary(saved.sources), source_summary(working.sources)
        if before == after:
            before += "\n\nThe source file, extracted evidence, captions or page reviews differ."
            after += "\n\nThe source file, extracted evidence, captions or page reviews differ."
        add("Uploaded reports and supporting evidence", before, after, force=True)
    return tuple(changes)


def _show_images(references, loader):
    if not references:
        return
    if loader is None:
        st.caption("Open the report preview to compare these pictures/pages.")
        return
    for n, reference in enumerate(references[:4]):
        try:
            st.image(loader(reference), caption=f"Picture/page {n + 1}", width="stretch")
        except (OSError, ValueError):
            st.warning(f"Picture/page {n + 1} could not be displayed. Your saved content has not been changed.")
    if len(references) > 4:
        st.caption(f"Showing the first 4 of {len(references)} pictures/pages. Use the full report preview to check the rest.")


def render_conflict_comparison(working, snapshot, *, working_asset_loader=None, saved_asset_loader=None):
    """Display differences only. The caller owns revision acceptance and saving."""
    st.write(f"Saved version {snapshot.revision} · entered editor: {snapshot.entered_editor or snapshot.draft.prepared_by or 'Not recorded'}")
    if snapshot.generated_at:
        st.caption("Saved at " + snapshot.generated_at)
    st.caption("Compare the saved version on the left with your current work on the right. Nothing is merged or saved here.")
    changes = compare_drafts(working, snapshot.draft)
    if not changes:
        st.info("The report content matches the saved version. You can accept that version below.")
    for change in changes:
        with st.expander(change.title):
            left, right = st.columns(2)
            with left:
                st.markdown("**Saved report**")
                st.text(change.saved)
                _show_images(change.saved_images, saved_asset_loader)
            with right:
                st.markdown("**Your current work**")
                st.text(change.working)
                _show_images(change.working_images, working_asset_loader)
    return changes
