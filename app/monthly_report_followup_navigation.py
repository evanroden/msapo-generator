"""Exact native follow-up routing; never changes content or approval."""
from dataclasses import asdict, dataclass
from hashlib import sha256
from html import escape
import json
from uuid import uuid4
from app.monthly_report_correction_targets import report_identity


def digest(value):
    return sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class FollowupTarget:
    report: str
    item_key: str
    revision: str
    category: str
    reason: str
    sources: str

    @property
    def token(self):
        return digest(asdict(self))


def followup_target(draft, item, reason):
    return FollowupTarget(report_identity(draft), item.key, digest(asdict(item)),
                          item.category, reason, digest([s.fingerprint for s in draft.sources]))


def resolve_followup(draft, target):
    from app.monthly_report_followups import problem_details
    if not isinstance(target, FollowupTarget) or target.report != report_identity(draft):
        return None
    keys = [item.key for item in draft.follow_ups]
    if len(keys) != len(set(keys)):
        return None
    matches = [item for item in draft.follow_ups if item.key == target.item_key]
    if len(matches) != 1:
        return None
    item = matches[0]
    section = 'issues' if item.category == 'issue' else 'proposals'
    if (not item.included or item.category not in ('issue', 'proposal')
            or not any(s.key == section and s.included for s in draft.sections)
            or followup_target(draft, item, target.reason) != target
            or target.reason not in {p.reason for p in problem_details(item, draft)}):
        return None
    return item


NOTICE = 'This item changed or is unavailable. Your edits remain here; use its current warning.'


def queue_navigation(prefix, target, scope):
    import streamlit as st
    from app.monthly_report_issues import _action_scope
    draft = st.session_state.get(prefix + '_draft')
    st.session_state.pop(prefix + '_followup_navigation_open', None)
    st.session_state.pop(prefix + '_followup_navigation_pending', None)
    if draft is None or _action_scope(draft, prefix) != scope or resolve_followup(draft, target) is None:
        st.session_state[prefix + '_followup_navigation_notice'] = NOTICE
        return
    st.session_state[prefix + '_followup_navigation_pending'] = {
        'target': target, 'scope': scope, 'nonce': uuid4().hex}


def consume_after_capture(draft, prefix, category):
    """Called by the authoritative owner AFTER pending fields, BEFORE pagination."""
    import streamlit as st
    from app.monthly_report_issues import _action_scope
    from app.monthly_report_followups import FOLLOWUP_PAGE_SIZE
    request = st.session_state.get(prefix + '_followup_navigation_pending')
    if not isinstance(request, dict):
        return
    target = request.get('target')
    if not isinstance(target, FollowupTarget) or target.category != category:
        return
    st.session_state.pop(prefix + '_followup_navigation_pending', None)
    item = resolve_followup(draft, target)
    if (item is None or request.get('scope') != _action_scope(draft, prefix)
            or not isinstance(request.get('nonce'), str) or not request['nonce']):
        st.session_state[prefix + '_followup_navigation_notice'] = NOTICE
        return
    visible = [i for i in draft.follow_ups if i.category == category and (i.included or category == 'proposal')]
    index = next(n for n, i in enumerate(visible) if i.key == item.key)
    page_key = prefix + ('_issues_page' if category == 'issue' else '_carried_proposal_page')
    st.session_state[page_key] = index // FOLLOWUP_PAGE_SIZE + 1
    st.session_state[prefix + '_followup_navigation_open'] = request


def field_markup(prefix, item, reason, field_key, kind='textarea'):
    import streamlit as st
    request = st.session_state.get(prefix + '_followup_navigation_open')
    if not isinstance(request, dict):
        return ''
    target = request.get('target')
    if not isinstance(target, FollowupTarget) or target.item_key != item.key or target.reason != reason:
        return ''
    if target.revision != digest(asdict(item)):
        st.session_state.pop(prefix + '_followup_navigation_open', None)
        st.session_state[prefix + '_followup_navigation_notice'] = NOTICE
        return ''
    st.session_state.pop(prefix + '_followup_navigation_open', None)
    identity = sha256(prefix.encode()).hexdigest()[:24]
    destination = 'report-correction-' + digest((prefix, target.token))
    return ('<span class="enfra-picture-correction" id="' + destination +
        '" data-report-identity="' + identity + '" data-field-kind="' + kind +
        '" data-field-key="' + escape(field_key, quote=True) + '" aria-hidden="true"></span>' +
        '<a class="enfra-page-correction-request" data-report-identity="' + identity +
        '" data-token="' + escape(request['nonce'], quote=True) + '" href="#' + destination + '" hidden></a>')


def render_links(check, draft, prefix):
    import streamlit as st
    from app.monthly_report_issues import _action_scope
    for target in check.targets:
        item = resolve_followup(draft, target)
        if item is None:
            continue
        with st.container(key='monthly_followup_warning_' + target.token):
            st.button('Correct ' + ('issue' if item.category == 'issue' else 'proposal') + ' · ' +
                      {'description':'description', 'status':'status', 'evidence':'evidence',
                       'sources':'source links', 'decision':'decision', 'period':'update month'}[target.reason],
                      key=prefix + '_followup_correction_' + target.token,
                      on_click=queue_navigation, args=(prefix, target, _action_scope(draft, prefix)))
