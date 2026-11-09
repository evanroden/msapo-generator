"""Explicit whole-template fallback; never a cover-only or artwork approval."""
from dataclasses import replace


def verified_master_template(profile, template=""):
    from app import monthly_report_designs as designs
    if not template:
        digest = designs.master_state().get("default", "")
        if not digest:
            return ""
        template = designs.MASTER_PREFIX + digest
    if not template.startswith(designs.MASTER_PREFIX):
        raise ValueError("Choose a verified ENFRA master template.")
    source = designs.source_for(replace(profile, template=template))
    if source is None:
        raise ValueError("The selected ENFRA template is unavailable. Your upload and review are unchanged.")
    return template


def fallback_profile(profile, template):
    """Keep imported schema/provenance; explicitly replace the entire design pin."""
    return replace(profile, template=verified_master_template(profile, template))


def validate_fallback_sections(draft):
    """A template choice cannot silently discard an authored extra section."""
    from app.monthly_report_designs import master_section_order
    supported = set(master_section_order(draft.profile))
    blocks = {block.key: block for block in draft.blocks if block.source != 'Omit'}
    missing = [section.title for section in draft.sections if section.included and section.key not in supported
               and any((block := blocks.get(spec.key)) is not None
                       and any((block.text.strip(), block.rows, block.extra_tables,
                                block.asset_hashes, block.org_nodes))
                       for spec in section.blocks)]
    if missing:
        raise ValueError('The selected ENFRA template has no layout for ' + ', '.join(missing)
                         + '. Your upload and reviewed content are unchanged; keep the original design or choose a compatible template.')
