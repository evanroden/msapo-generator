---
document_type: implementation_commit_handoff
repository: evanroden/msapo-generator
branch: main
base_commit: 284eca796b6cb3b28d89e64bf6b3ab8e96d33aac
date: 2026-08-14
workflow: purchase_order
change_type: extraction_accuracy
status: shipped
reported_by: David Siegal (contract administration), relayed by the product owner
evidence: one real Trane service quote, UMMC CH-3, quote ID 377277
follows: COMMIT_NOTES_2026-08-13_ASSET_AND_ROUTING_ACCURACY.md
closes: "the open question in section 4 of the 2026-08-13 notes"
---

# Commit notes: routing reads the scope, not the terms and conditions

## 1. LLM quick context

A contract administrator questioned a submitted PO:

> *"Just to confirm, this new Trane quote is Labor, since I think scope says
> so?" … "It'll be an object account (OA) of 5511 then."*

The operator had entered `5301 - ON`. **The tool produced that same wrong
answer**, so this was a tool defect, not a data-entry slip. Confirmed by running
the actual quote through `infer_purchase_route`.

The 2026-08-13 notes ended by saying the remaining unknown needed *"one real
quote plus what it should have been."* This is that quote. **It closes that
question**, and the answer was not what those notes predicted.

### 1.1 Invariants

1. **Routing classifies what the vendor is selling**, not the contract governing
   what happens if it goes wrong.
2. **A genuine exclusion inside the proposal still counts.** "Labor by others"
   written into the scope must still suppress the labour route. This fix must
   not swing the error the other way.
3. **The cut is conservative in both directions.** No heading, or too little
   text before one, returns the document unchanged.

## 2. Cause

The rules were reading the whole extracted document.

| | characters | share |
|---|---|---|
| Full OCR text | 45,866 | 100% |
| The actual proposal | 3,563 | 8% |
| Trane's standard terms | 42,303 | **92%** |

That boilerplate contains the exact phrases the routing rules key on. Two
independent misreads came out of it:

| Phrase | Section it lives in | Effect |
|---|---|---|
| "modifications made by others to Company's equipment" | warranty exclusions, three pages past the scope | matched `_LABOR_DISCLAIMED_RE`'s bare `\bby\s+others\b`, silencing the labour signal for the **entire document** |
| "the cost of transporting a part requiring service" — plus 13 more | terms, warranty, limitation of liability | made `_is_parts_purchase` true |

With labour suppressed and parts asserted, the quote fell through to
`materials_purchase` → `5301-MATERIALS` / `ON - STANDARD PO UNDER $25K`.

**One cause, two symptoms.** Neither regex was wrong about the text it matched.
Both were reading text that was never the job.

### 2.1 Why the document-level disclaimer made it worse

`_LABOR_DISCLAIMED_RE` was deliberately built to cross sentence boundaries, so
that "Supply parts. Labor by others." negates the whole quote. That is correct
for a two-line proposal. Applied to a document with 42,000 characters of
appended legalese, it means **any quote whose terms say "by others" anywhere is
declared labour-free** — and Trane's standard terms say it. So does most
vendors' boilerplate.

## 3. Fix

`app.po_rules.scope_region` trims trailing boilerplate before the rules run,
cutting at the first terms / warranty / limitation-of-liability / indemnity
heading. `infer_purchase_route` is its only caller.

Guarded by `_MIN_SCOPE_CHARS = 200`: a heading landing in the first couple of
hundred characters means the scope probably follows the terms, so the document
is returned whole rather than gutted (invariant 3).

Result on the reported quote — 2,510 characters kept of 45,866:

```
BEFORE  materials_purchase  ->  5301-MATERIALS      / ON - STANDARD PO UNDER $25K
AFTER   onsite_labor        ->  5511-SUBCONTRACTOR  / 03 - MSAPO (SERVICE)
```

which is what the contract administrator said it should be.

## 4. Why the existing corpus could not have caught this

`test_route_inference_over_a_realistic_quote_corpus` passes 13/13 and still
does. Its entries are **bare scope text with no attached terms** — which is not
what OCR hands us in production. The corpus tested the rules against the input
they were designed for, and that input was unrepresentative in exactly the
dimension that mattered.

That is the generalisable lesson here, and it is worth more than the fix: a
corpus assembled from the same mental model as the code under test will agree
with it. This defect needed a real document.

## 5. Asset identification was already correct

Worth recording, since it was the other half of the 2026-08-13 work. The quote
names `CH-3` explicitly and the exact-tag stage resolved it. The lowest-numbered
fallback added on 2026-08-13 correctly **did not** engage — it runs only when
the exact-tag and scorer stages both decline. Left alone it would have answered
`FWP-1`, so the gating is load-bearing, not incidental.

## 6. Tests

`tests/test_scope_region.py`, 12 cases:

- the reported shape routes to labour and yields 5511 / MSAPO end to end;
- the scope alone routed correctly all along — appending boilerplate is what
  flipped it (pins the **cause**, not just the symptom);
- each of seven boilerplate headings ends the scope;
- a document with no boilerplate is untouched;
- terms preceding the scope do not gut it;
- **"Labor by others" inside the proposal still routes to materials**
  (invariant 2).

**No fixture is copied from the real document.** The repository forbids
committing real quotes; these reproduce its *structure* — a short labour scope
followed by boilerplate carrying the two trigger phrases.

## 7. What was NOT verified

- **Whether the analyzer (`analyze_quote`) makes the same mistake is still
  untested.** It reads the same unsegmented text, so it plausibly does, but this
  environment has no API key. If it does, `scope_region` is the obvious place to
  apply there too — deliberately not done blind.
- **Only one vendor's boilerplate was examined.** The seven headings cover the
  common forms, but a vendor whose terms carry no recognised heading still gets
  the whole document classified.
- **No measurement of how many past submissions this affected.** The reported
  one is confirmed; the rate is unknown.

## 8. Deliberately unchanged

- `_LABOR_DISCLAIMED_RE`, `_LABOR_AS_PRODUCT_RE`, `_PARTS_OF_EQUIPMENT_RE`. None
  was wrong about the text it matched. Narrowing them to dodge boilerplate would
  have weakened them on the scope, where they are correct and needed.
- The routing matrix, the asset stages, and the corpus test.
- The `route_uncertain` cross-check from 2026-08-13 stays as the backstop for
  whatever this does not catch.
