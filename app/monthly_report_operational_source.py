"""Explicit, default-off original/rendition lookups at operation boundaries.

Never expose a DocxInspection facade with original SHA and derivative facts.
CompatibilityView keeps both truthful inspections. Consumers explicitly choose
source references or rendered occurrences, and rederive before using either.
"""
from contextlib import contextmanager
from dataclasses import dataclass, replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from app.monthly_report_compatibility_view import (
    CompatibilityError, CompatibilityView, rederive_compatibility_view,
)


def verify_source_view(original_path, expected_view):
    if not isinstance(expected_view, CompatibilityView):
        raise CompatibilityError('An explicit verified native source view is required.')
    fresh = rederive_compatibility_view(original_path, expected_view.receipt_bytes)
    if fresh != expected_view:
        raise CompatibilityError('The native source-view bytes, mapping or inspection changed.')
    return fresh


def verify_inspection(original_path, inspection, source_view):
    fresh = verify_source_view(original_path, source_view)
    if inspection != fresh.original_inspection:
        raise CompatibilityError('The source inspection is not the immutable original audit.')
    return fresh


def receipt_record(view):
    return json.loads(view.receipt_bytes)


def lookup_original(view, identity):
    """Return the explicit original binding and truthful rendered occurrence."""
    binding = next((b for b in view.bindings if b.original_id == identity), None)
    if binding is None:
        raise CompatibilityError('Unknown original occurrence in native source view.')
    item = next((i for i in view.rendition_inspection.items if i.id == binding.rendition_id), None)
    if binding.rendition_id is not None and item is None:
        raise CompatibilityError('Missing rendition occurrence in native source view.')
    return binding, item


def operational_items(original_inspection, source_view=None):
    """Explicit planning projection, not a substituted source inspection.

    Native diagnostic resolution affects planning only; original audit records
    remain unchanged in the view and persisted inspection. No asset approval is
    created. Final operation boundaries must independently rederive the view.
    """
    if source_view is None:
        return original_inspection.items
    if original_inspection != source_view.original_inspection:
        raise CompatibilityError('Planning requires the original source inspection.')
    result = []
    for original in original_inspection.items:
        binding, rendered = lookup_original(source_view, original.id)
        # Preserve unrelated original routing metadata. Only the proved native
        # diagnostic gains its derivative furniture kind/note in this projection.
        result.append(replace(original, kind=rendered.kind, note=rendered.note)
                      if binding.status == 'resolved' and rendered is not None else original)
    return tuple(result)


def original_reference(inspection, rendered_item, source_view=None):
    if source_view is None:
        return f'docx:{inspection.sha256}:{rendered_item.id}'
    if inspection != source_view.rendition_inspection:
        raise CompatibilityError('Render references require the truthful rendition inspection.')
    binding = next((b for b in source_view.bindings if b.rendition_id == rendered_item.id), None)
    if binding is None or rendered_item not in inspection.items:
        raise CompatibilityError('Unbound rendered occurrence cannot inherit a source reference.')
    return f'docx:{source_view.original_inspection.sha256}:{binding.original_id}'


def cache_identity(inspection, source_view=None):
    return (inspection.sha256 if source_view is None else
            source_view.original_inspection.sha256 + ':' + source_view.rendition_inspection.sha256
            + ':' + source_view.receipt_sha256)


@contextmanager
def rendition_file(view):
    """Only verified callers may use this disposable path; never persist it."""
    with TemporaryDirectory(prefix='native-operation-') as temporary:
        path = Path(temporary)/'rendition.docx'
        path.write_bytes(view.rendition_bytes)
        yield path


@dataclass(frozen=True)
class _VerifiedOperation:
    original_path: Path
    view: CompatibilityView
    rendition_path: Path


def checked_operation(path, source_view, operation):
    if (not isinstance(operation, _VerifiedOperation) or Path(path).resolve() != operation.original_path
            or source_view is not operation.view):
        raise CompatibilityError('Invalid internal verified source operation.')
    return operation


@contextmanager
def verified_operation(path, source_view, inspection=None):
    view = verify_source_view(path, source_view)
    if inspection is not None and inspection != view.original_inspection:
        raise CompatibilityError('The source inspection is not the immutable original audit.')
    with rendition_file(view) as derivative:
        yield _VerifiedOperation(Path(path).resolve(), view, derivative)


@contextmanager
def _operation_from_verified_view(path, view):
    """Internal reuse after this public operation independently rederived view."""
    with rendition_file(view) as derivative:
        yield _VerifiedOperation(Path(path).resolve(), view, derivative)
