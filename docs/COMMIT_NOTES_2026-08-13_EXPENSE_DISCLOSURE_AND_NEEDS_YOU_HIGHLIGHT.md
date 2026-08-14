---
document_type: implementation_commit_handoff
repository: evanroden/msapo-generator
branch: main
merge_commit: 15c478a7852a16d736948b21dcc88585d4e3a62d
merge_commit_subject: "Expense disclosure + highlight fields that still need a value (#45)"
pull_request: 45
base_commit: 53a910c6eb4ebfe1c0c935c5125f81e61fa869c5
date: 2026-08-13
workflow: cross_cutting
change_type: progressive_disclosure_and_affordance
status: shipped
merge_method: merge_commit_not_squash
reported_by: product owner
follows: COMMIT_NOTES_2026-08-12_TOUCH_AND_RENDERER_RELIABILITY.md
implementation_commits:
  - sha: 75c78f25491d8e888970fe54d2581eb15ab68f65
    subject: Collapse confirmed expense report details behind one line
  - sha: c7e772e51c841db0ba87801b1718140032f52e19
    subject: Highlight fields that still need a value, in both workflows
---

# Commit notes: expense progressive disclosure and Needs-You highlighting

## 1. LLM quick context

Two requests, one shipped change set.

1. *"Go ahead and start the expense workflow streamlining. It's super important
   all of the functionality is preserved, though, especially the scope,
   inclusions, exclusions, and all of the fields as editable."*
2. *"Needs You fields should be highlighted until filled, in both workflows."*

### 1.1 Invariants

1. **Nothing is removed and nothing becomes read-only.** Streamlining here means
   *placement*, never *capability*. Every field renders exactly once and stays
   editable. This constraint was stated explicitly and is the reason the detail
   block was **wrapped** rather than rewritten.
2. **A field that has a safe default is not something the operator must supply**,
   so it is never flagged and never holds a panel open.
3. **The highlight is transient with no state of its own.** It is recomputed from
   live values every rerun, so it clears on the run after a field is filled.
4. **A scoping control that silently defaults stays visible.** See §2.3.
5. **"Needs a value" must not look identical to "currently editing."** See §3.2.

## 2. Expense step 2: collapsed behind one line

### 2.1 Cause

The purchase-order workflow already had progressive disclosure — a needs banner,
a `questions` container for unresolved values, and a collapsed "Change a value
the tool already filled" panel. The expense workflow had none of it: step 2
rendered ten controls on every visit whether or not the operator had anything to
decide.

For a returning operator on a remembered account, all of it is already known —
employee name, employee number, home business unit, approver name and email come
from that account's confirmed history. They were shown anyway.

### 2.2 Fix

`app/expense_ui.py` computes `_outstanding_details` **before** rendering, from
`session_state`, then chooses the wrapper:

```python
if _outstanding_details:
    _details_panel = st.container()
else:
    _details_panel = st.expander(...)
with _details_panel:
    ...
```

The block that follows is the original code, indented. Same fields, same order,
same two-column layout.

Placement must be computed before rendering because **a widget's value does not
exist in `session_state` until it renders** — reading it afterwards to decide the
wrapper is a frame too late.

The five conditions are the fields with no safe default: employee name, employee
number, approver name, approver email, and the satellite office *only when the
check is being mailed to one*. Report date, mail destination and service year all
carry defaults and never hold the panel open.

### 2.3 Deliberately outside the panel: the account selector

It drives job numbers, cost coding, and which approvers are remembered, and it
has **no placeholder**, so it silently defaults to the first contract. Hiding a
silently-defaulted scoping control would reproduce the unknown-facility hazard
already fixed on the purchase-order side. It stays visible.

### 2.4 Two reverted attempts — read before retrying either

Both were implemented, caught, and backed out. The reasons are structural and
still apply.

**(a) Rebuilding the expense draft mirror.** Reverted because a test written for
it caught it wiping a half-finished report: `workflow_mode` updates *before* the
rerun, so the mirror saw the new mode against the old draft. A completion marker
was tried as a fix and still broke via `pages/2_Smartsheet_PO.py`, which enters
the same state from a different path.

**(b) The first disclosure attempt.** Reverted because the test could not engage
the collapsed path at all. Cause: it wrote widget keys *after* render. The
approver selectbox uses `index=None` with `accept_new_options=True`, and a
post-render write to that key is discarded — while still firing its `on_change`,
which clears the paired email field. This is why §2.2 computes placement from
state read before the render, and it is the general shape of the hazard on this
page.

## 3. Needs-You highlighting, both workflows

### 3.1 Cause

The "Needed from you" banner said that *something* was missing but not *which*
field, leaving the operator to scan the form.

### 3.2 Fix and the visual choice

`app/ui_highlight.py` (new) emits CSS targeting Streamlit's `st-key-<key>` class
— the only supported hook for styling one specific widget.

It is a **separate module** because `app.web_ui` imports `app.expense_ui`, so the
expense workflow cannot import back from the purchase-order page without a cycle.

The mark is a **yellow left bar plus a faint tint**, reusing the needs-banner
idiom so the banner and the fields it refers to read as one system. Deliberately
*not* a full outline: a full outline in the same colour is already the focus
ring, and invariant 5 forbids "needs a value" looking identical to "currently
editing".

Emitting from the caller rather than baking it into `CUSTOM_CSS` is what makes
the highlight transient (invariant 3).

### 3.3 The two workflows reach it differently, on purpose

| Workflow | Key(s) emitted | Why |
|---|---|---|
| Purchase order | the single static container key `po_needs_you` | The page already routes each field to `questions if needs.X else corrections`, so that container holds exactly what is still in question. A field leaves the highlight by *moving to corrections*. |
| Expense | the four/five field keys directly | That block has no resolved/unresolved split, so the keys come from the same five conditions that decide whether the panel collapses (§2.2). |

On the PO side the container also always holds the requester, which is required
and has no resolved/unresolved split of its own. So: highlight the whole group
while the tool is still asking something, otherwise highlight just the requester
while it is blank — never both, so no field carries two nested bars.

### 3.4 A silent failure, found by checking rather than assuming

The first version highlighted the requester by **its own** key and rendered
nothing at all — no error, no highlight, nothing to notice in a green test run.

Streamlit rewrites any character outside `[A-Za-z0-9_-]` to a hyphen when it
builds the class. The requester key embeds the contract name, so
`requester_<tok>_Rochester Regional Health` becomes the class
`st-key-requester_<tok>-Rochester-Regional-Health`, while the emitted selector
still contained spaces and matched nothing.

Two changes came out of it:

1. `_class_name()` **normalises** a key the way Streamlit does, rather than
   discarding anything not already selector-safe — so a caller whose key embeds a
   contract name still works.
2. The PO path keys off the container's **static** key, which needs no
   normalisation at all.

`test_widget_keys_are_normalised_the_way_streamlit_names_the_class` pins the
normalisation *specifically because the failure mode is silent*.

## 4. Verification

Verified **in a real browser**, not only by `AppTest`: the expected four expense
fields carry the bar and the satellite office does not; filling one clears its
bar while the others keep theirs; the PO requester is highlighted while blank and
clean once filled; and the expanded first-run expense view keeps the same
arrangement as before the wrap.

Tests: `tests/test_expense_disclosure.py`, `tests/test_needs_value_highlight.py`,
`tests/test_expense_draft_state.py`.

Browser checking is what caught §3.4, and it is the third silent failure on this
project that a green suite did not. Treat "tests pass" as insufficient evidence
for anything that renders.

## 5. What was NOT verified

- **No touch-device pass.** The bar was checked on desktop only; the iPad
  behaviour from the previous change set was not re-exercised here.
- **No colour-contrast measurement.** `#FCFCF3` against the theme background was
  chosen to match the existing banner, not measured against WCAG.

## 6. Deliberately unchanged

- Every expense field, its editability, its order, and the two-column layout.
- The account selector's placement (§2.3).
- Fields with safe defaults, which remain unflagged and never hold the panel open.
- **`st.form` batching was NOT adopted.** It is not a safe drop-in here — the
  reasoning is in §5 of `COMMIT_NOTES_2026-08-12_TOUCH_AND_RENDERER_RELIABILITY.md`.
  Receipt-as-card also remains open.
