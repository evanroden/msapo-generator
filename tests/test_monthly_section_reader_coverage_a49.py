"""A49: bounded document-reader receipts; synthetic evidence only, never paid requests."""
from dataclasses import replace
import re

import pytest

from app import monthly_report_ai as ai
from app import monthly_report_structured_uploads as reader
from app.monthly_report_model import ReportSource, ResolvedBlock
from app.monthly_report_sources import SourceContent


SOURCE_ID = "a" * 64


def source(count, *, length=80):
    pages = tuple(
        (f"Inspection page {n:03d}: motor was not repaired; replacement is pending.").ljust(length, ".")
        for n in range(1, count + 1)
    )
    return SourceContent(ReportSource(
        SOURCE_ID, "synthetic.txt", SOURCE_ID, ".txt", page_texts=pages
    ))


def refs(payload):
    return [(sid, int(n)) for block in payload
            for sid, n in re.findall(
                r"SOURCE ([a-f0-9]{64}) PAGE (\d+)\n", block.get("text", "")
            )]


def model_payload(payload, *, duplicate=False):
    values = [
        {"source": sid, "page": page,
         "text": f"Inspection page {page:03d}: motor was not repaired; replacement is pending.",
         "row": [], "include_page": False}
        for sid, page in refs(payload)
    ]
    return {"items": values + values if duplicate else values,
            "pages": [{"source": sid, "page": page, "result": "read"}
                      for sid, page in refs(payload)]}


@pytest.mark.parametrize("count,expected", [(24, [20, 4]), (96, [20, 20, 20, 20, 16])])
def test_all_eligible_pages_are_read_in_bounded_chunks_and_receipted(monkeypatch, count, expected):
    content = source(count)
    chunks, skipped, eligible = reader.reader_page_plan((content,), "activity_summary")
    assert list(map(len, chunks)) == expected
    assert len(eligible) == count and not skipped
    payloads = reader.reader_batches(None, (content,), "activity_summary")
    assert [len(refs(p)) for p in payloads] == expected
    assert all(sum(len(block.get("text", "")) for block in p
                   if block.get("text", "").startswith("SOURCE ")) <= 60_000
               for p in payloads)
    calls = []
    def fake_read(payload):
        calls.append(refs(payload))
        return model_payload(payload, duplicate=True)
    monkeypatch.setattr(ai, "request_json", fake_read)
    value = reader.read_batches(payloads)
    assert len(calls) == len(expected)
    assert len(value["items"]) == count  # Same source/page/quote is idempotent.
    assert len(value["coverage"]) == len(expected)
    assert all(receipt["status"] == "processed" for receipt in value["coverage"])
    merged, pages, accepted, failed, skipped = reader.reader_coverage_update(
        (content,), "activity_summary", value,
        ResolvedBlock("activity_summary", "This month", text="Human notes remain."),
    )
    assert len(accepted) == count and not failed and not skipped
    assert len(set(accepted)) == count and pages == {}
    assert merged.text.startswith("Human notes remain.")
    assert "not repaired" in merged.text
    assert len(merged.references) == count


def test_failed_middle_chunk_isolated_and_only_that_chunk_retried(monkeypatch):
    content = source(96)
    first_payloads = reader.reader_batches(None, (content,), "activity_summary")
    calls = []
    fail = {21}
    def sometimes_fails(payload):
        first = refs(payload)[0][1]
        calls.append(first)
        if first in fail:
            raise ValueError("synthetic provider timeout")
        return model_payload(payload)
    monkeypatch.setattr(ai, "request_json", sometimes_fails)
    first = reader.read_batches(first_payloads)
    current, _, processed, failed, skipped = reader.reader_coverage_update(
        (content,), "activity_summary", first)
    assert len(processed) == 76 and len(failed) == 20 and not skipped
    assert calls == [1, 21, 41, 61, 81]
    assert not any("page 021" in text for text in current.text.split("\n\n"))
    fail.clear()
    retry = reader.reader_batches(None, (content,), "activity_summary", page_refs=failed)
    assert len(retry) == 1 and refs(retry[0]) == list(failed)
    again = reader.read_batches(retry)
    final, _, newly_done, retry_failed, retry_skipped = reader.reader_coverage_update(
        (content,), "activity_summary", again, current)
    assert len(newly_done) == 20 and not retry_failed and not retry_skipped
    assert len(set((*processed, *newly_done))) == 96
    assert calls == [1, 21, 41, 61, 81, 21]
    assert len(final.references) == 96
    assert reader.reader_coverage_update(
        (content,), "activity_summary", again, final)[0].text == final.text


def test_unreadable_or_oversized_page_has_explicit_skip_not_silent_drop():
    content = source(24)
    pages = list(content.source.page_texts)
    pages[7] = "X" * 60_001
    content = replace(content, source=replace(content.source, page_texts=tuple(pages)))
    chunks, skipped, eligible = reader.reader_page_plan((content,), "activity_summary")
    assert len(eligible) == 24 and skipped == ((SOURCE_ID, 8),)
    assert sorted(n for chunk in chunks for _, n in chunk) == [n for n in range(1, 25) if n != 8]
    assert len(reader.reader_batches(None, (content,), "activity_summary")) == 2


def test_untrusted_model_cannot_claim_another_page_and_good_sibling_survives(monkeypatch):
    content = source(24)
    def fake(payload):
        if refs(payload)[0][1] == 1:
            return {"items": [{"source": SOURCE_ID, "page": 24,
                               "text": "Inspected motor.", "row": []}]}
        return model_payload(payload)
    monkeypatch.setattr(ai, "request_json", fake)
    value = reader.read_batches(reader.reader_batches(None, (content,), "activity_summary"))
    _, _, done, failed, _ = reader.reader_coverage_update(
        (content,), "activity_summary", value)
    assert len(done) == 4 and len(failed) == 20
    assert set(done).isdisjoint(failed)


def test_invalid_grounding_is_failed_chunk_without_erasing_good_siblings(monkeypatch):
    content = source(24)
    def fake(payload):
        if refs(payload)[0][1] == 1:
            bad = model_payload(payload)
            bad["items"][0]["text"] = "Replaced motor."
            return bad
        return model_payload(payload)
    monkeypatch.setattr(ai, "request_json", fake)
    value = reader.read_batches(reader.reader_batches(None, (content,), "activity_summary"))
    block, _, done, failed, _ = reader.reader_coverage_update((content,), "activity_summary", value)
    assert len(done) == 4 and len(failed) == 20
    assert "Replaced motor." not in block.text


def test_missing_pages_do_not_create_paid_calls(monkeypatch):
    content = source(0)
    assert reader.reader_batches(None, (content,), "activity_summary") == ()
    monkeypatch.setattr(ai, "request_json", lambda _: pytest.fail("unexpected paid call"))
    assert reader.read_batches(())["coverage"] == []
    with pytest.raises(ValueError, match="not eligible"):
        reader.reader_batches(None, (content,), "activity_summary", page_refs=((SOURCE_ID, 1),))


def test_unavailable_scanned_only_page_is_skipped_without_model_request(monkeypatch):
    content = source(1)
    content = replace(content, source=replace(content.source, needs_vision=(1,)))
    payload = [{"type": "text", "text":
                f"SOURCE {SOURCE_ID} PAGE 1\n{content.source.page_texts[0]}"},
               {"type": "text", "text":
                "Visual reading unavailable within the image allowance. Use native text only; never include this original page."}]
    monkeypatch.setattr(ai, "request_json", lambda _: pytest.fail("image-only batch may not call model"))
    value = reader.read_batches((payload,))
    assert len(value["coverage"]) == 1
    block, _, processed, failed, skipped = reader.reader_coverage_update(
        (content,), "activity_summary", value)
    assert not processed and not failed and skipped == ((SOURCE_ID, 1),)
    assert not block.references and not block.text


def test_cached_partial_coverage_survives_retry_and_reload(monkeypatch):
    content = source(24)
    fail = {21}
    def model(payload):
        if refs(payload)[0][1] in fail:
            raise ValueError("synthetic interrupted chunk")
        return model_payload(payload)
    monkeypatch.setattr(ai, "request_json", model)
    first = reader.read_batches(reader.reader_batches(None, (content,), "activity_summary"))
    _, _, processed, failed, _ = reader.reader_coverage_update(
        (content,), "activity_summary", first)
    assert len(processed) == 20 and len(failed) == 4
    fail.clear()
    second = reader.read_batches(reader.reader_batches(None, (content,),
                                                        "activity_summary", page_refs=failed))
    cache = reader.merge_reader_coverage(first, second)
    assert len(cache["coverage"]) == 24
    assert len(cache["items"]) == 24
    block, _, done, failed_again, skipped = reader.reader_coverage_update(
        (content,), "activity_summary", cache)
    assert len(done) == 24 and not failed_again and not skipped
    # Retrying stale failures must never erase already completed cache receipts.
    again = reader.merge_reader_coverage(cache, first)
    assert len(again["items"]) == 24
    assert len(reader.reader_coverage_update(
        (content,), "activity_summary", again)[2]) == 24
    assert len(block.references) == 24


def test_model_must_receipt_every_page_even_when_no_facts(monkeypatch):
    content = source(24)
    def incomplete(payload):
        complete = model_payload(payload)
        complete["pages"] = complete["pages"][:-1]
        return complete
    monkeypatch.setattr(ai, "request_json", incomplete)
    payloads = reader.reader_batches(None, (content,), "activity_summary")
    result = reader.read_batches(payloads)
    assert len(result["coverage"]) == 2
    assert all(receipt["status"] == "failed" for receipt in result["coverage"])
    assert not result["items"]
    _, _, done, failed, _ = reader.reader_coverage_update(
        (content,), "activity_summary", result)
    assert not done and len(failed) == 24


def test_model_unreadable_page_receipted_as_manual_review_not_fact(monkeypatch):
    content = source(24)
    def unreadable(payload):
        result = model_payload(payload)
        if refs(payload)[0][1] == 1:
            result["pages"][2]["result"] = "unreadable"
            result["items"] = [i for i in result["items"] if i["page"] != 3]
        return result
    monkeypatch.setattr(ai, "request_json", unreadable)
    value = reader.read_batches(reader.reader_batches(None, (content,), "activity_summary"))
    _, _, accepted, failed, skipped = reader.reader_coverage_update(
        (content,), "activity_summary", value)
    assert len(accepted) == 23 and not failed and skipped == ((SOURCE_ID, 3),)


def test_page_plan_keeps_main_routing_filter_for_non_activity_sources():
    content = source(1)
    content = replace(content, source=replace(content.source, classification="Water treatment"))
    chunks, skipped, eligible = reader.reader_page_plan((content,), "activity_summary")
    assert not chunks and not skipped and not eligible
    assert reader.reader_batches(None, (content,), "activity_summary") == ()
