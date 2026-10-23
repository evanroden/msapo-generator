"""Reviewed, revision-bound replacement of one shared logo, never its scope."""
from dataclasses import asdict, dataclass, replace
from datetime import date
import hashlib
import hmac

from app import monthly_report_branding as branding
from app import monthly_report_library as library

OWNER_VARIANT_PREFIX = "Owner-provided approved variant. "


@dataclass(frozen=True)
class LogoReplacementReview:
    original: branding.BrandLogo
    replacement: branding.BrandLogo
    revision: int
    actor: str
    token: str


def prepare_replacement(logo, revision, raw, *, actor, checked_on, source_note):
    """Bind the displayed before/after review to exact bytes and metadata."""
    actor = library._confirmation(actor, True)
    if type(revision) is not int or revision < 1:
        raise ValueError("Reload the saved logo collection before replacing a logo.")
    note = source_note.strip()
    if not note:
        raise ValueError("Describe the owner-provided artwork and its approval.")
    date.fromisoformat(checked_on)
    reference = library.asset_reference(raw, "png")
    branding._image(raw, reference)
    replacement = replace(logo, asset=reference, checked_on=checked_on,
        source_note=OWNER_VARIANT_PREFIX + note,
        # This is a retained brand reference, not a claim that uploaded bytes
        # were downloaded from that page. The admin UI labels it accordingly.
        asset_url=logo.source_url)
    branding._logos([asdict(replacement) | {"contracts": list(replacement.contracts)}])
    payload = {"schema": 1, "original": asdict(logo), "replacement": asdict(replacement),
               "revision": revision, "actor": actor}
    token = hashlib.sha256(library._json(payload)).hexdigest()
    return LogoReplacementReview(logo, replacement, revision, actor, token)


def replace_selected_logo(key, raw, *, expected_revision, actor, checked_on,
                          source_note, review_token, confirmed):
    """Only one asset/provenance changes; all other records remain exact copies."""
    actor = library._confirmation(actor, confirmed)
    current = branding.load_branding()
    if current is None or current.revision != expected_revision:
        raise library.RevisionConflict("The shared logos changed. Reload and review this logo again.")
    original = next((logo for logo in current.logos if logo.key == key), None)
    if original is None:
        raise ValueError("The selected shared logo is no longer available.")
    review = prepare_replacement(original, expected_revision, raw, actor=actor,
                                 checked_on=checked_on, source_note=source_note)
    if (not isinstance(review_token, str) or not review_token.isascii()
            or not hmac.compare_digest(review.token, review_token)):
        raise ValueError("This logo review changed. Review the selected logo again before saving.")
    logos = tuple(review.replacement if logo.key == key else logo for logo in current.logos)
    # Validate all retained artwork before the first write. Passing these exact
    # verified bytes also avoids a later per-record read failure after the new
    # asset has already been installed. The writer rechecks revision under its
    # ordinary lock, so a concurrent catalog edit cannot publish this snapshot.
    assets = {review.replacement.asset: raw}
    for logo in current.logos:
        if logo.key != key:
            assets[logo.asset] = branding.read_logo(logo)
    return branding.save_branding(logos, assets,
        expected_revision=expected_revision, actor=actor, confirmed=True,
        action="replace-logo:" + key)
