"""Acknowledge only an exact interrupted browser save, without relaxing CAS."""
from dataclasses import dataclass
from uuid import uuid4

from app import monthly_report_active_work as active
from app.monthly_report_model import ReportDraft


@dataclass(frozen=True)
class PendingSave:
    scope: tuple
    token: str
    draft: ReportDraft
    fingerprint: str
    assets: tuple[tuple[str, bytes], ...]
    expected_revision: int
    expected_generation: str
    base_snapshot_revision: int
    operation_id: str


def acknowledge(state, prefix, scope, token):
    """Replay the immutable request before acknowledging either local guard.

    Session-state access can yield to a new Streamlit run. Keep this receipt
    until BOTH guard assignments finish; never mutate it through an unguarded
    object reference or substitute newly delivered edits into its request.
    """
    key = prefix + "_pending_browser_save"
    request = state.get(key)
    if request is None:
        return None
    if (not isinstance(request, PendingSave) or request.scope != scope or request.token != token
            or (request.draft.profile.contract, request.draft.profile.key, request.draft.period.key) != scope[:3]
            or request.draft.fingerprint != request.fingerprint):
        raise active.ActiveWorkConflict("A pending browser save belongs to another report incarnation.")
    saved = active.save(token, request.draft, expected_revision=request.expected_revision,
                        expected_generation=request.expected_generation,
                        base_snapshot_revision=request.base_snapshot_revision,
                        assets=dict(request.assets), operation_id=request.operation_id)
    state[prefix + "_active_sequence"] = saved.revision
    state[prefix + "_active_generation"] = saved.generation
    state.pop(key, None)
    return saved


def save(state, prefix, scope, token, draft, assets):
    acknowledge(state, prefix, scope, token)
    request = PendingSave(scope, token, draft, draft.fingerprint, tuple(sorted(assets.items())),
                          state.get(prefix + "_active_sequence", 0),
                          state.get(prefix + "_active_generation", ""),
                          state[prefix + "_revision"], uuid4().hex)
    # Installation is a yield point BEFORE any side effect. A replacement run
    # may replay this exact request under the journal lock, even if the old
    # runner is still finishing it; only one revision can be committed.
    state[prefix + "_pending_browser_save"] = request
    return acknowledge(state, prefix, scope, token)
