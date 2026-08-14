---
document_type: implementation_commit_handoff
repository: evanroden/msapo-generator
branch: main
merge_commit: d8d317331d9f6ac6dce7a7e1cb1125275ec37186
merge_commit_subject: "Fix asset identification and PO routing defaults (#46)"
pull_request: 46
base_commit: 15c478a7852a16d736948b21dcc88585d4e3a62d
date: 2026-08-13
workflow: purchase_order
change_type: extraction_accuracy
status: shipped
merge_method: merge_commit_not_squash
reported_by: product owner, from production use
follows: COMMIT_NOTES_2026-08-13_EXPENSE_DISCLOSURE_AND_NEEDS_YOU_HIGHLIGHT.md
implementation_commits:
  - sha: e89795ccf07afb69e1df76c2e92d510cb2dd5016
    subject: Resolve a named equipment type to the lowest-numbered unit at that site
  - sha: 6b4ec14f10df8c6b82f355e79a92fe2f4f8b0f3e
    subject: Stop Object Account and Agreement Type defaulting to Subcontractor/MSAPO
---

# Commit notes: asset identification and PO routing accuracy

## 1. LLM quick context

Two production complaints, both about the tool producing a confident answer that
was wrong:

1. *"The tool basically never correctly identifies the asset, even when the scope
   summary the tool creates is pretty clear that it's, for example, work on a
   boiler or a chiller."*
2. *"The tool selecting '5511-Subcontractor' and '03 - MSAPO (Service)' every
   single time isn't acceptable, since that's not always what this is."*

The second turned out to have **three** causes, not the one or two suspected. The
largest was structural and had nothing to do with guess quality.

### 1.1 Invariants

1. **A named equipment type resolves to the lowest-numbered unit that EXISTS at
   that site.** Not unit one — United Memorial's chillers start at CH-2.
2. **Two named types stay unresolved.** Guessing between a chiller and a cooling
   tower is worse than leaving it blank. This preserves the rule established by
   the AS-1 air-separator fix.
3. **Object Account and Agreement Type derive from exactly one routing answer**,
   and that answer must be *visible* to the operator whenever it is uncertain.
4. **Uncertainty is measured by disagreement** between the analyzer's guess and
   the deterministic text rules — two independent signals that already exist.
5. **Group A means a COMPLETE item.** Parts, kits and components for one are
   materials.

## 2. Asset identification

### 2.1 Cause

`app/asset_guess.guess_asset_uid` ends with:

```python
if best_score < 45 or best_score == runner_up:
    return None
```

A tie returns nothing. Scope text saying "boiler work" scores every boiler at the
site identically, so it tied and gave up. The module's own comment stated this as
intent: equipment type alone "often ties across several rows and therefore will
not select an arbitrary unit."

That refusal was correct when written — it is what stopped the alphabetically
first air separator (AS-1) being presented as a confident identification. It was
never revisited when the cost became apparent.

A second miss sat underneath it. Matching required the registry's **whole**
equipment description to appear in the text. Scope says "chiller", the registry
says "Centrifugal Chiller", so `"CENTRIFUGAL CHILLER" in "...chiller..."` is
False and the tie was rarely even reached.

### 2.2 Fix

A third stage in `_asset_options` (app/web_ui.py), running **only** when the
exact-tag and scorer stages both decline, backed by
`app.asset_guess.lowest_numbered_of_type`.

Matching is on the equipment's **head noun**, which is what lets "chiller" reach
"Centrifugal Chiller". The head noun also keeps the near-misses apart, because
theirs differ:

| Registry equipment | Head noun |
|---|---|
| Centrifugal Chiller | CHILLER |
| Chiller VFD | VFD |
| Cooling Tower | TOWER |
| Cooling Tower Fill | FILL |

Grouping by noun rather than description also means a site holding both a
Centrifugal and an Absorption Chiller still resolves to one chiller group.

Sorting is on the trailing integer. Registries are inconsistent about padding —
Rochester General uses `CH-01`, United Memorial uses `CH-2` — and a string sort
would rank `CH-10` ahead of `CH-2`.

### 2.3 Verified against the live registry

| Scope | Site | Resolves to |
|---|---|---|
| "Replace chiller compressor bearings" | UMMC | `CH-2` |
| "Cooling tower repair and cleaning" | UMMC | `CT-1` |
| "Steam boiler teardown and reassembly" | UMMC | `B-1` |
| "Centrifugal chiller annual service" | RGH | `CH-01` |
| "Steam boiler tube replacement" | RGH | `B-01` |

**United Memorial has no CH-1** — its chillers are CH-2 and CH-3. That is the
whole reason this is a registry lookup rather than string arithmetic, and
`test_united_memorial_has_no_chiller_one` pins the fact so a registry change
cannot quietly invalidate the CH-2 expectation.

## 3. PO routing — three causes

### 3.1 Cause A: the control was never shown (structural, and the largest)

`app/web_ui.py` rendered the route selector unconditionally inside `corrections`
— the **collapsed** "Change a value the tool already filled" panel:

```python
with corrections:
    purchase_route = st.selectbox("How will this work or purchase be handled? *", ...)
```

So whatever the tool picked went through unseen unless the operator thought to
open that panel. **This alone accounts for a wrong answer arriving "every single
time", independent of how good the guess was.** It is also the cause that no
amount of prompt tuning would have addressed.

**Fix.** Two independent signals already exist for this field — the analyzer's
`purchase_route_guess` and the deterministic `infer_purchase_route`. Their
disagreement is now the confidence measure:

```python
route_uncertain = model_route not in PURCHASE_ROUTES or model_route != inferred_route
...
with questions if route_uncertain else corrections:
```

When they differ, or the analyzer offered nothing, the selector renders in the
visible, highlighted questions container with a caption stating it drives Object
Account and Agreement Type. When both agree it stays in corrections, so the
confident cases do not nag.

### 3.2 Cause B: the fallback was biased toward labour (measured)

Run against a corpus of realistic quote texts, `infer_purchase_route` got **2 of
11 wrong**, both in the same direction — false `onsite_labor`, which is exactly
the reported symptom:

```
"Quote for pipe fittings and valve repair kits, shipped to site."
"Supply replacement service parts for the boiler. Labor by others."
```

Both failed the same way: a labour word used as a **noun modifier**. "repair
kits" and "service parts" name products, not work. `_LABOR_RE` matches
`repair|service|install|inspect`, all of which appear in nearly any equipment
quote.

The second example failed a second way too. `_has_affirmative_match` examines a
48-character window around each match, which cannot reach across the sentence
boundary to "Labor by others."

**Fix.** `_labor_signal` now strips product phrases before matching
(`_LABOR_AS_PRODUCT_RE`) and honours a document-level disclaimer
(`_LABOR_DISCLAIMED_RE`) covering "labor by others", "installation by others",
"no onsite labor" regardless of sentence position.

### 3.3 Cause C: parts for Group A equipment classified as equipment

Surfaced while fixing B. "Supply replacement service parts for the boiler"
matched the Group A keyword list on "boiler" and routed to `5302-EQUIPMENT`.
Group A means a **complete** item; parts for one are materials.

**Fix.** `_is_parts_purchase` guards the Group A branch.

**Watch this one.** The first version matched the idiom "part **of** the quoted
scope", which turned "Installation is not part of the quoted scope. Supply one
new boiler." into a materials purchase — swinging the error the opposite way. An
existing test caught it. `_PART_OF_IDIOM_RE` now excludes the idiom, and that
case is in the corpus.

### 3.4 Result

The corpus passes **13/13** and ships as
`tests/test_po_rules.py::test_route_inference_over_a_realistic_quote_corpus`,
covering every one of the four routes and pinning both false-labour patterns plus
the parts-versus-equipment distinction.

## 4. What was NOT verified — read before assuming coverage

**Whether the analyzer itself over-applies the labour rule is untested.** That
requires an API key this environment does not have, so no real quote was ever run
through `analyze_quote`.

Causes B and C were reproduced and fixed directly. Cause A is structural and
verifiable by reading the render path. The disagreement check in 3.1 is what
makes the untested question stop mattering: if the model and the text rules
diverge, the operator is asked rather than a silent default being accepted.

If routing is still wrong after this, the next step is **one real quote plus what
it should have been**. That distinguishes "the model guessed wrong and the text
rules agreed with it" — the only remaining path to a silent wrong answer — from
the three causes fixed here.

## 5. Deliberately unchanged

- The exact-tag and scorer stages of asset matching. A quote naming `CWP-7` still
  resolves by tag, not by type.
- The conservative refusal to choose between two named equipment types.
- The routing matrix itself, which already matched the policy documents exactly:
  `onsite_labor`→`5511-SUBCONTRACTOR`/`03 - MSAPO (SERVICE)`,
  `onsite_rental`→`5411-OUTSIDE RENTALS`/`03 - MRAPO (RENTAL)`,
  `equipment_purchase`→`5302-EQUIPMENT`/`OR - EQUIPMENT PO`,
  `materials_purchase`→`5301-MATERIALS` with the $25,000 split. **No mapping was
  edited** — only which route gets selected, and whether the operator sees it.
