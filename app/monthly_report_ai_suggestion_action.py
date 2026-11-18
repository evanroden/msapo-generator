"""One-action, revision-bound acceptance of displayed optional AI wording.

No report/source data is mutated here; callers replace their draft only after a
successful exact-revision check.  The native paragraph editor remains the owner
of subsequent manual corrections and review.
"""
from dataclasses import replace

from app import monthly_report_ai as ai
from app.monthly_report_correction_targets import report_identity


class SuggestionConflict(ValueError):
    """The rendered action no longer belongs to the current report/editor."""


def request_receipt(draft, existing, target, scope):
    """Freeze the CURRENT target before a cache lookup or asynchronous read."""
    return (
        report_identity(draft),
        scope,
        target,
        existing.fingerprint if existing is not None else None,
        tuple((source.id, source.sha256, source.fingerprint) for source in draft.sources),
    )


def finish_receipt(request, suggestion):
    if (not isinstance(request, tuple) or len(request) != 5
            or request[2] != suggestion.key):
        return None
    return (*request[:3], suggestion.fingerprint, *request[3:])


def capture(draft, existing, suggestion, scope):
    return finish_receipt(request_receipt(draft, existing, suggestion.key, scope), suggestion)


def verify(receipt, draft, existing, suggestion, scope):
    if not isinstance(receipt, tuple) or len(receipt) != 6:
        raise SuggestionConflict(
            "The suggestion has no current revision receipt. Request wording again; your report was not changed."
        )
    fresh = capture(draft, existing, suggestion, scope)
    if receipt[0] != fresh[0] or receipt[1] != fresh[1] or receipt[2] != fresh[2]:
        raise SuggestionConflict(
            "This suggestion belongs to another report, site or month. Current wording was kept."
        )
    if receipt[3] != fresh[3] or receipt[5] != fresh[5]:
        raise SuggestionConflict(
            "The suggestion or its source evidence changed. Read current evidence and redraft; your wording was kept."
        )
    if receipt[4] != fresh[4]:
        raise SuggestionConflict(
            "Your section changed after the suggestion was requested. The newer manual wording was kept; redraft before accepting."
        )


def checked_suggestion(suggestion, texts, sources):
    """Validate the actual displayed choice against authoritative source facts."""
    if (not isinstance(texts, (tuple, list)) or not suggestion.ai_paragraphs
            or len(texts) != len(suggestion.ai_paragraphs)):
        raise ValueError("The suggestion is missing paragraphs. Existing wording was kept.")
    paragraphs = []
    for paragraph, value in zip(suggestion.ai_paragraphs, texts):
        if not isinstance(value, str) or not value.strip() or len(value) > 2000:
            raise ValueError("A suggested paragraph is missing or too long. Existing wording was kept.")
        text = ai.clean_text(value)
        if text != value:
            raise ValueError("Review the exact displayed wording: contact data or surrounding whitespace requires correction.")
        if not text or ai.contains_price(text):
            raise ValueError("A suggested paragraph has invalid content or pricing. Existing wording was kept.")
        paragraphs.append(replace(paragraph, text=text))
    candidate = replace(
        suggestion,
        text="\n".join("- " + paragraph.text for paragraph in paragraphs),
        ai_paragraphs=tuple(paragraphs),
    )
    candidate = ai.refresh_evidence(candidate, sources)
    return ai.reviewed_block(candidate, sources)


def accept(draft, existing, suggestion, receipt, scope, texts, *,
           append=True, pending_manual=False):
    """One deliberate acceptance; a late result or live editor input cannot win."""
    verify(receipt, draft, existing, suggestion, scope)
    if pending_manual:
        raise SuggestionConflict(
            "A newer manual edit is waiting in this section. It was kept; review the current wording and request a new suggestion."
        )
    candidate = checked_suggestion(suggestion, texts, draft.sources)
    if append and existing:
        existing_lines = existing.text.splitlines()
        candidate_lines = candidate.text.splitlines()
        if candidate_lines and all(line in existing_lines for line in candidate_lines):
            raise SuggestionConflict(
                "This suggestion is already in the report. No duplicate wording was added."
            )
    return ai.apply_suggestion(existing, candidate, draft.sources, append=append)
