# Smartsheet job-number catalog and Unity disambiguation

**Date:** 2026-08-10
**Applies to:** Purchase Order Process Control quote analysis, review, export,
and Smartsheet custom-URL prefilling

## Source of truth

`app/job_numbers.py` contains all 87 exact JOB NUMBER dropdown values supplied
by the product owner. Preserve their capitalization, spaces, hyphens, slashes,
and wording. Exported values must be members of that catalog; do not accept or
manufacture free-text variants.

The review UI narrows the catalog to the selected account when its name can be
matched. RRH shows only its four RRH-prefixed values. A non-RRH account with no
safe catalog match retains the complete dropdown rather than receiving a
guessed value. An exact job identifier such as `VI100018` in the quote may
select its unique catalog row; category wording alone must not invent a job.

## Unity means two different organizations

The three JOB NUMBER values beginning `Unity` belong to **Unity Health System
in Arkansas**:

- `Unity 695000029 - CCJ`
- `Unity VI100036 - O&M`
- `Unity VI100056 - ISDC`

They do not belong to Unity Hospital or Unity Specialty Hospital in the RRH
account. The Rochester, New York facilities use the four `RRH-...` job values.

Vendor quotes for the Rochester facility may say only “Unity.” The analyzer
must use account and location evidence—including RRH, Rochester, New York, Long
Pond Road, Genesee Street, ZIP code, and the selected account—before resolving
that word. Bare “Unity” must never cause selection of the Arkansas account or
an Arkansas Unity job number. When evidence remains ambiguous, the account and
job number remain required visible operator choices.

This distinction is embedded directly in the quote-analysis system prompt and
covered by tests that require the RRH and Arkansas option groups to stay
disjoint.
