"""Guided template promotion preserves only exact reviewed source artwork."""
from dataclasses import replace
import json

import pytest

from app import monthly_report_library as library, monthly_report_designs as designs
from app.monthly_report_guided import complete_guided_sections
from app.monthly_report_native_layout import build_native_docx
from app.monthly_report_preview import section_preview_docx
from test_monthly_report_native_art_review import sample
from test_monthly_report_native_art_lifecycle import save_sample


def guided(draft):
    draft = complete_guided_sections(draft)
    return replace(draft, profile=designs.pin(draft.profile, latest_master=True, preserve_legacy=False))


def test_saved_source_art_survives_normal_guided_template_pin(sample):
    path, view, profile, period, inventory, receipt = sample
    draft, loader = save_sample(sample)
    manifest = library._profile_path(profile.contract, profile.key) / 'manifest.json'
    before = manifest.read_bytes()
    opened = guided(library.load_imported_draft(profile.contract, profile.key))
    assert opened.profile.template == designs.PREFIX + profile.imported_from
    assert draft.profile.template != opened.profile.template
    assert library.verified_render_source_view(opened, path) == view
    assert build_native_docx(opened, path, asset_loader=loader)
    assert section_preview_docx(opened, 'cover', loader)
    assert section_preview_docx(opened, 'activity', loader)
    assert manifest.read_bytes() == before
    assert library.imported_native_art_review(profile.contract, profile.key, period, source_view=view) == receipt


@pytest.mark.parametrize('change', ['title', 'facility', 'scope', 'period', 'other_source', 'builtin', 'master', 'other_legacy'])
def test_pin_promotion_does_not_relax_scope(sample, change):
    path, view, profile, period, inventory, receipt = sample
    draft, _ = save_sample(sample)
    opened = guided(draft)
    if change == 'title': opened = replace(opened, profile=replace(opened.profile, title='Different title'))
    elif change == 'facility': opened = replace(opened, profile=replace(opened.profile, facilities=(replace(profile.facilities[0], title='Other site'),)))
    elif change == 'scope': opened = replace(opened, profile=replace(opened.profile, scope_type='regional'))
    elif change == 'period': opened = replace(opened, period=replace(period, month=10))
    else:
        template = {'other_source': designs.PREFIX + 'f' * 64, 'builtin': designs.BUILTIN_PREFIX + profile.template,
                    'master': designs.MASTER_PREFIX + profile.imported_from, 'other_legacy': 'other-template'}[change]
        opened = replace(opened, profile=replace(opened.profile, template=template))
    with pytest.raises(ValueError): library.verified_render_source_view(opened, path)


def test_changed_effective_saved_design_cannot_claim_original_pin_equivalence(sample):
    path, view, profile, period, inventory, receipt = sample
    draft, _ = save_sample(sample)
    opened = guided(draft)
    folder = designs._directory(profile.contract)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'manifest.json').write_text(json.dumps({'schema': 1, 'profiles': {profile.key: 'f' * 64}, 'default': '', 'revision': 1}))
    with pytest.raises(ValueError, match='template scope'):
        library.verified_render_source_view(opened, path)


def test_already_pinned_browser_work_recovers_without_receipt_migration(sample):
    from app import monthly_report_active_work as active_work
    path, view, profile, period, inventory, receipt = sample
    draft, loader = save_sample(sample)
    opened = guided(draft)
    token = 'a' * 32
    active_work.save(token, opened, expected_revision=0, base_snapshot_revision=0)
    recovered = active_work.load(token, profile.contract, profile.key, period).draft
    recovered = replace(recovered, profile=designs.pin(recovered.profile, preserve_legacy=True))
    assert recovered == opened
    assert library.verified_render_source_view(recovered, path) == view
    assert section_preview_docx(recovered, 'activity', loader)
    assert library.imported_native_art_review(profile.contract, profile.key, period, source_view=view) == receipt


def test_explicit_reviewed_source_stays_exact_and_cannot_reverse_to_implicit(sample):
    from app import monthly_report_native_art_review as art
    path, view, profile, period, inventory, receipt = sample
    implicit = profile.template
    profile = replace(profile, template=designs.PREFIX + profile.imported_from)
    inventory = art.native_art_inventory(path, view, profile, period)
    ids = tuple(item.original_id for item in inventory.occurrences)
    receipt = art.make_native_art_review(inventory, actor='Synthetic Operator',
        keep_native_ids=ids, visually_reviewed_ids=ids, suitable_ids=ids)
    draft, _ = save_sample((path, view, profile, period, inventory, receipt))
    assert library.verified_render_source_view(guided(draft), path) == view
    with pytest.raises(ValueError, match='template scope'):
        library.verified_render_source_view(replace(draft, profile=replace(profile, template=implicit)), path)


def test_real_guided_ui_opens_import_and_renders_pinned_activity(sample, monkeypatch):
    from datetime import date
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    from app import monthly_report_guided as guided_ui, monthly_report_section_preview_ui
    from test_monthly_report_ui import choose_report
    from app.contracts import RRH_CONTRACT
    from app import monthly_report_native_art_review as art
    path, view, profile, period, inventory, receipt = sample
    profile = replace(profile, contract=RRH_CONTRACT)
    inventory = art.native_art_inventory(path, view, profile, period)
    ids = tuple(item.original_id for item in inventory.occurrences)
    receipt = art.make_native_art_review(inventory, actor='Synthetic Operator',
        keep_native_ids=ids, visually_reviewed_ids=ids, suitable_ids=ids)
    draft, loader = save_sample((path, view, profile, period, inventory, receipt))
    # Inspect the real workspace initialization without queuing background PDF
    # conversion; exercise its resulting draft through the real Word preview.
    monkeypatch.setattr(guided_ui, 'operator_today', lambda tz: date(2026, 10, 7))
    monkeypatch.setattr(monthly_report_section_preview_ui, 'render_section_preview', lambda *a, **kw: None)
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / 'run_web.py', default_timeout=60).run()
    app.segmented_control[0].set_value('Monthly report').run()
    choose_report(app, profile.facilities[0].title)
    assert not app.exception
    drafts = [value for key, value in app.session_state.filtered_state.items()
              if key.endswith('_draft') and getattr(value, 'profile', None) is not None]
    opened = next(value for value in drafts if value.profile.key == profile.key)
    assert opened.profile.template == designs.PREFIX + profile.imported_from
    assert library.verified_render_source_view(opened, path) == view
    assert section_preview_docx(opened, 'activity', loader)
