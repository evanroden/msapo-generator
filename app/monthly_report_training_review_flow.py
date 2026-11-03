"""Durable, explicit report-only Training source decisions and publication."""
from dataclasses import asdict, replace
from datetime import date
from hashlib import sha256
import json

from app.monthly_report_row_review_receipts import decoded as saved_receipt

from app import monthly_report_sources as sources
from app.monthly_report_model import ReportTable, ResolvedBlock
from app.monthly_report_training import is_matrix_reference
from app.monthly_report_training_import import (
    training_tables, review_training_table, training_review_record, restore_training_review,
    correct_training_row, exclude_training_row, accepted_training_block,
)


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))



def decoded(text):
    """Check saved structure/row integrity without current report authorization."""
    message = "The saved Training review is damaged or exceeds its budget. Original evidence is unchanged."
    if not isinstance(text, str) or len(text) > 4_000_000:
        raise ValueError(message)
    try:
        value = json.loads(text)
        if (not isinstance(value, dict) or type(value.get("schema")) is not int
                or value["schema"] != 1 or value.get("kind") != "training"
                or any(not isinstance(value.get(key), str) for key in
                       ("scope", "source_id", "source_fingerprint", "filename"))
                or type(value.get("table")) is not int or value["table"] < 1
                or not isinstance(value.get("history"), list)
                or any(not isinstance(key, str) for key in value["history"])
                or len(set(value["history"])) != len(value["history"])
                or "published" not in value):
            raise ValueError(message)
        record = value["record"]
        if (not isinstance(record, dict) or type(record.get("schema")) is not int
                or record["schema"] != 1 or not isinstance(record.get("sha256"), str)):
            raise ValueError(message)
        # Validate serialized container types before restoration: tuple("")
        # would otherwise normalize malformed empty strings into valid tuples.
        raw = record.get("review")
        text_list = lambda items: isinstance(items, list) and all(isinstance(item, str) for item in items)
        text_rows = lambda items: isinstance(items, list) and all(text_list(row) for row in items)
        if (not isinstance(raw, dict) or not isinstance(raw.get("source"), dict)
                or not isinstance(raw.get("rows"), list)
                or not isinstance(raw.get("unmatched"), list)
                or any(not text_list(raw.get(key)) for key in
                       ("original_columns", "normalized_columns", "issues"))
                or not text_rows(raw.get("original_rows"))
                or not text_list(raw["source"].get("columns"))
                or not text_rows(raw["source"].get("rows"))):
            raise ValueError(message)
        for row in raw["rows"]:
            if (not isinstance(row, dict) or not isinstance(row.get("origin"), dict)
                    or not text_list(row.get("values")) or not text_list(row.get("issues"))
                    or not text_rows(row.get("corrections"))
                    or any(len(change) != 2 for change in row["corrections"])
                    or not text_list(row["origin"].get("columns"))
                    or not text_list(row["origin"].get("cells"))):
                raise ValueError(message)
        for unmatched in raw["unmatched"]:
            if (not isinstance(unmatched, list) or len(unmatched) != 3
                    or type(unmatched[0]) is not int or not text_list(unmatched[1])
                    or not isinstance(unmatched[2], str)):
                raise ValueError(message)
        review = restore_training_review(record)
        strings = lambda items: isinstance(items, tuple) and all(isinstance(item, str) for item in items)
        source = review.source
        if (any(not isinstance(getattr(source, key), str) for key in
                ("filename", "source_id", "source_sha256", "source_fingerprint", "reference", "word_item_id", "word_section"))
                or type(source.number) is not int or source.number < 1
                or type(source.native_word) is not bool
                or type(review.native_layout_confirmed) is not bool
                or not strings(source.columns) or any(not strings(row) for row in source.rows)
                or not strings(review.original_columns) or not strings(review.normalized_columns)
                or any(not strings(row) for row in review.original_rows)
                or not strings(review.issues)):
            raise ValueError(message)
        for row in review.rows:
            origin = row.origin
            if (type(row.excluded) is not bool or not isinstance(row.status, str)
                    or not strings(row.values) or not strings(row.issues)
                    or any(not strings(change) or len(change) != 2 for change in row.corrections)
                    or type(origin.table_number) is not int or type(origin.row_number) is not int
                    or not strings(origin.columns) or not strings(origin.cells)):
                raise ValueError(message)
        for number, cells, reason in review.unmatched:
            if type(number) is not int or not strings(cells) or not isinstance(reason, str):
                raise ValueError(message)
        if (review.source.source_id != value["source_id"]
                or review.source.source_fingerprint != value["source_fingerprint"]
                or review.source.filename != value["filename"]
                or review.source.number != value["table"]
                or set(value["history"]) - {row.key for row in review.rows}):
            raise ValueError(message)
        published = value["published"]
        if published is not None:
            if (not isinstance(published, dict)
                    or any(not isinstance(published.get(key), str)
                           for key in ("decision", "block"))
                    or any(type(published.get(key)) is not bool
                           for key in ("replace_source", "replace_matrix"))
                    or not isinstance(published.get("before"), dict)):
                raise ValueError(message)
            from app.monthly_report_library import block_from_dict
            before = published["before"]
            if any(not isinstance(before.get(key), str) for key in ("key", "source", "text")):
                raise ValueError(message)
            block_from_dict(before).fingerprint
        return value
    except (ValueError, KeyError, TypeError, AttributeError, IndexError,
            OverflowError, RecursionError) as exc:
        raise ValueError(message) from exc


def revision(value):
    return sha256(encoded(value).encode()).hexdigest()


def scope(draft):
    return revision((draft.profile.contract, draft.profile.key,
                     [asdict(site) for site in draft.profile.facilities], draft.period.key))


def source_content(draft, source):
    raw = sources.source_bytes(draft.profile, source)
    content, _ = sources.ingest(draft.profile, source.filename, raw)
    return replace(content, source=source)


def _identity(value):
    return tuple(value.get(key) for key in ("kind", "scope", "source_id", "source_fingerprint", "table"))


def saved_review(draft, source, number):
    identity = ("training", scope(draft), source.id, source.fingerprint, number)
    found = [saved_receipt(raw) for raw in draft.source_row_reviews
             if _identity(saved_receipt(raw)) == identity]
    if len(found) > 1:
        raise ValueError("Multiple saved Training reviews need reconciliation.")
    return validate(draft, found[0]) if found else None


def validate(draft, value):
    if value.get("schema") != 1 or value.get("kind") != "training" or value.get("scope") != scope(draft):
        raise ValueError("This Training review belongs to a different report or month.")
    source = next((item for item in draft.sources if item.id == value.get("source_id")), None)
    if source is None or source.fingerprint != value.get("source_fingerprint"):
        raise ValueError("The Training source changed or was removed. Existing corrections are retained.")
    review = restore_training_review(value["record"])
    if (review.period_key != draft.period.key or review.source.source_id != source.id
            or review.source.source_fingerprint != source.fingerprint
            or review.source.number != value.get("table")):
        raise ValueError("The Training review lost its source or reporting-month identity.")
    if len(encoded(value)) > 4_000_000:
        raise ValueError("This Training review exceeds its saved-review budget.")
    return value


def store_review(draft, value, expected_revision=""):
    validate(draft, value)
    records = list(draft.source_row_reviews)
    matches = [index for index, text in enumerate(records)
               if _identity(saved_receipt(text)) == _identity(value)]
    if len(matches) > 1:
        raise ValueError("Multiple saved Training reviews need reconciliation.")
    index = matches[0] if matches else None
    previous = saved_receipt(records[index]) if index is not None else None
    if (revision(previous) if previous else "") != expected_revision:
        raise ValueError("The saved Training review changed. Reopen its current rows.")
    if index is None:
        records.append(encoded(value))
    else:
        records[index] = encoded(value)
    if len(records) > 100 or sum(map(len, records)) > 16_000_000:
        raise ValueError("The report's source-review budget is full. Existing reviews are unchanged.")
    return replace(draft, source_row_reviews=tuple(records))


def prepare_review(draft, source, number, source_year=None):
    table = next((table for table in training_tables(source_content(draft, source), draft.profile)
                  if table.number == number), None)
    if table is None:
        raise ValueError("This Training source table is unavailable.")
    review = review_training_table(table, draft.profile, draft.period, source_year=source_year)
    return {"schema": 1, "kind": "training", "scope": scope(draft), "source_id": source.id,
            "source_fingerprint": source.fingerprint, "table": number, "filename": source.filename,
            "record": training_review_record(review), "history": [], "published": None}


def change_row(draft, value, key, changes, *, excluded=False, historical=False):
    validate(draft, value)
    review = restore_training_review(value["record"])
    # Restoring a deliberately omitted row remains explicit and revalidates it.
    review = replace(review, rows=tuple(replace(row, excluded=excluded) if row.key == key else row
                                       for row in review.rows))
    review = correct_training_row(review, key, changes, expected_revision=review.revision,
                                  profile=draft.profile, period=draft.period)
    history = set(value["history"])
    history.discard(key)
    if historical and not excluded:
        row = next(row for row in review.rows if row.key == key)
        if review.kind != "events" or not row.values[1] or date.fromisoformat(row.values[1]) >= draft.period.start:
            raise ValueError("Only a dated session before this reporting month can be selected as historical.")
        history.add(key)
    return {**value, "record": training_review_record(review), "history": sorted(history)}


def _selected_review(draft, value):
    review = restore_training_review(value["record"])
    history = []
    keys = set(value["history"])
    for row in review.rows:
        if row.key in keys and not row.excluded:
            if (review.kind != "events" or date.fromisoformat(row.values[1]) >= draft.period.start
                    or any(not issue.startswith("Historical/other-month session:") for issue in row.issues)):
                raise ValueError("Review historical dates, completion, people and hours before including them.")
            history.append(row.values)
            review = exclude_training_row(review, row.key, expected_revision=review.revision)
    if keys - {row.key for row in review.rows}:
        raise ValueError("A historical Training row is no longer in this review.")
    return review, tuple(history)


def publish_review(draft, value, *, expected_revision, expected_block, carry_prior=False,
                   replace_source=False, replace_matrix=False):
    validate(draft, value)
    source = next(s for s in draft.sources if s.id == value["source_id"])
    saved = saved_review(draft, source, value["table"])
    if saved is None or revision(saved) != expected_revision or revision(value) != expected_revision:
        raise ValueError("The Training review changed. Review the current decisions before including them.")
    block = next((b for b in draft.blocks if b.key == "training_summary"),
                 ResolvedBlock("training_summary", "This month"))
    if block.fingerprint != expected_block or block.source == "Omit":
        raise ValueError("Training changed or is left out. Review the current report before including these rows.")
    review, history = _selected_review(draft, value)
    original = next((t for t in training_tables(source_content(draft, source), draft.profile)
                     if t.number == review.source.number), None)
    if original != review.source:
        raise ValueError("The saved Training source no longer matches the reviewed cells.")
    decision = revision((value["record"], value["history"], carry_prior))
    previous = value["published"]
    if previous and previous["decision"] == decision:
        # Repeated import never restores rows subsequently edited or deleted.
        return draft
    if previous:
        if block.fingerprint != previous["block"]:
            raise ValueError("Training was edited after this import. Both the report and source corrections are retained; reconcile those edits before replacing rows.")
        # An unchanged published result can be revised by the same source review.
        # Restore only its exact pre-publication snapshot before reapplying the
        # explicit decisions. A manual edit/deletion above never takes this path.
        from app.monthly_report_library import block_from_dict
        block = block_from_dict(previous["before"])
        replace_source = replace_source or previous["replace_source"]
        replace_matrix = replace_matrix or previous["replace_matrix"]
    if review.issues or review.unmatched or not review.native_layout_confirmed:
        raise ValueError("Review the source's mapping, year and native layout before including rows.")
    if not history and not review.ready_for_import:
        raise ValueError("Review or omit unresolved Training rows before including this table.")
    if any(row.issues and not row.excluded for row in review.rows):
        raise ValueError("Review or omit unresolved Training rows before including this table.")
    source_refs = (review.source.reference,
                   "docx:" + review.source.source_sha256 + ":" + review.source.word_item_id)
    raw_tables = tuple(t for t in block.extra_tables if t.reference in source_refs)
    if raw_tables and not replace_source:
        raise ValueError("This source table is already visible. Confirm replacing that table with the reviewed rows.")
    proposed = replace(block, extra_tables=tuple(t for t in block.extra_tables if t.reference not in source_refs))
    if review.kind == "requirements" and replace_matrix:
        proposed = replace(proposed, extra_tables=tuple(t for t in proposed.extra_tables
                                                       if not is_matrix_reference(t.reference)))
    if any(not row.excluded for row in review.rows):
        proposed = accepted_training_block(review, proposed,
            expected_block_fingerprint=proposed.fingerprint, carry_prior_requirements=carry_prior)
    if history:
        reference = "training:history:v1:" + revision((source.id, value["table"]))[:24]
        table = ReportTable(("Historical training", *review.normalized_columns[1:]), history, reference)
        proposed = replace(proposed, extra_tables=(*proposed.extra_tables, table),
            references=tuple(dict.fromkeys((*proposed.references, review.source.reference))),
            source="This month", reviewed_fingerprint="", client_reviewed_fingerprint="")
    if review.kind == "requirements":
        from app.monthly_report_training import hospital_matrix
        from app.monthly_report_directory import load_directory
        matrix = next(t for t in proposed.extra_tables if is_matrix_reference(t.reference))
        if hospital_matrix(draft.profile, matrix, load_directory(draft.profile.contract)) != matrix:
            raise ValueError("Requirements are for hospital/client staff. Review the identified staff roles first.")
    result = replace(draft, blocks=tuple(proposed if b.key == block.key else b for b in draft.blocks)
                     if any(b.key == block.key for b in draft.blocks) else (*draft.blocks, proposed))
    value = {**value, "published": {"decision": decision, "block": proposed.fingerprint,
        "before": asdict(block), "replace_source": replace_source, "replace_matrix": replace_matrix}}
    return store_review(result, value, expected_revision)
