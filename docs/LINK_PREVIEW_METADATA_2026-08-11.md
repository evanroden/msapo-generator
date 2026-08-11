# Link-preview metadata and icon — implementation and commit handoff

**Date:** 2026-08-11

**Production URL:** `https://msapo-generator.onrender.com`

**Application name:** Process Control

**Deployment:** Render Docker web service, automatic deploy from `main`

## Purpose

Before this change, sharing the production URL produced an unhelpful preview:
the title was `Streamlit` and the site had only Streamlit's generic favicon.
The visible application eventually changed the browser title through
`st.set_page_config`, but that update happened only after JavaScript started.
Link-preview crawlers generally inspect the initial HTML response without
running the Streamlit client, so they never saw the application title and had
no description or preview image to use.

The application now exposes a complete identity in the initial HTML response:

| Field | Production value |
|---|---|
| HTML/Open Graph/Twitter title | `Process Control` |
| Description | `Prepare purchase-order requests and employee expense reports with guided review, generated files, and approval handoffs.` |
| Canonical URL | `https://msapo-generator.onrender.com/` |
| Favicon/app icon | `/process-control-icon-v1.png`, 512×512 PNG |
| Link-preview image | `/process-control-preview-v1.png`, 1200×630 PNG |
| Preview card type | Open Graph website + Twitter/X `summary_large_image` |
| Browser theme color | Ocean green `#092B24` |

The artwork uses the application's established ocean-green, safety-yellow,
white, and light-mint palette. It intentionally does **not** use the ENFRA name
or logo. That keeps the current alpha identity aligned with prior product-owner
direction while avoiding an unsupported trademark asset in the public repo.

`Process Control` is intentionally broader than `Purchase Order Process
Control`: the same URL now hosts both purchase-order and expense-reimbursement
workflows. The preview subtitle names both so a recipient knows what the link
opens before visiting it.

## File-by-file commit notes

| File | Exact responsibility and reason for change |
|---|---|
| `branding/process-control-icon.svg` | Editable vector source for the new `PC` identity. Rounded ocean-green field, safety-yellow edge/dot/rule, and high-contrast white monogram remain recognizable when reduced to favicon size. |
| `branding/process-control-icon.png` | 512×512 raster served to crawlers, browsers, and Apple touch-icon consumers. A PNG is used because crawler and favicon support is more predictable than an SVG-only identity. |
| `branding/process-control-preview.svg` | Editable vector source for the 1.904:1 social card. It names both workflows and avoids customer, account, employee, or vendor content. |
| `branding/process-control-preview.png` | 1200×630 raster used by Open Graph and Twitter/X. This is the widely supported large-card aspect and avoids platform-side text/layout generation. |
| `scripts/patch_streamlit_metadata.py` | Deterministically patches Streamlit's crawler-visible static shell, copies versioned images, replaces the generic favicon, removes conflicts, and fails the image build when required shell anchors/assets are absent. |
| `Dockerfile` | Runs the patch only after dependencies and repository assets exist. The build, rather than a live request, owns this deterministic mutation. |
| `app/web_ui.py` | Synchronizes the JavaScript/runtime browser-tab title and favicon with the raw crawler shell. The rest of the PO and expense UI is untouched. |
| `tests/test_link_preview_metadata.py` | Adds behavioral, idempotence, malformed-shell, asset-integrity, and Docker-ordering regression coverage. |
| `tests/test_public_repository_hygiene.py` | Narrowly allows the two intentional PNG artifacts. It does not relax the prohibition against receipt/quote screenshots and other uploaded/generated images. |
| `README.md` | Links this handoff and lists the metadata patch and public branding assets in the architecture map. |

No expense calculation, quote analysis, Smartsheet field, email handoff,
memory table, receipt image, or persistent-disk data path changes in this
commit. There is no database migration and no new environment variable.

## Runtime and build architecture

`app/web_ui.py` still calls `st.set_page_config`. That is the authoritative
runtime browser-tab configuration and uses the same local PNG icon. It is not
sufficient for link previews by itself.

`scripts/patch_streamlit_metadata.py` is the crawler-facing layer. During the
Docker build, after `COPY . .`, the script locates Streamlit's installed
`static/index.html`, copies the public PNG assets into that static directory,
replaces the default title, removes conflicting title/description/icon/social
tags, and inserts the metadata block. Streamlit serves that patched shell and
the copied assets directly.

The build sequence is deliberately:

1. install the pinned Streamlit dependency range;
2. copy repository source and branding assets;
3. run `python scripts/patch_streamlit_metadata.py`;
4. start Streamlit normally at runtime.

Patching at image-build time means no request middleware, proxy, injected
JavaScript, or additional web service is needed. The public application URL
does not change.

## Asset files

- `branding/process-control-icon.svg` is the editable 512×512 source.
- `branding/process-control-icon.png` is the browser/crawler artifact.
- `branding/process-control-preview.svg` is the editable 1200×630 source.
- `branding/process-control-preview.png` is the social-card artifact.

The deployed filenames contain `-v1`. This makes a future artwork revision
explicit and gives preview services a new image URL instead of relying on a
stale cached image at an unchanged URL. If the artwork changes, increment both
the filename constant and the copied asset URL (`v2`, `v3`, and so forth).

## Metadata ownership

The patcher owns and normalizes these tags:

- HTML `title`;
- standard `description`, `application-name`, Apple title, and theme color;
- canonical link, favicon, shortcut icon, and Apple touch icon;
- Open Graph type, site name, title, description, URL, image, MIME type,
  dimensions, and alternative text;
- Twitter/X card, title, description, image, and alternative text.

It removes older instances of those tags before insertion. Running the patch
twice therefore produces byte-identical HTML rather than duplicate metadata.
Unknown meta/link elements from a future Streamlit release are preserved.

## Failure modes and controls

| Failure mode | Control |
|---|---|
| Streamlit changes the shell and removes `<title>` or `</head>` | Build fails instead of deploying a partially patched page. |
| A branding PNG is missing | Build fails with the exact missing path. |
| Script runs more than once | Old managed block/tags are removed; idempotence test requires byte-identical output. |
| Browser runtime title diverges from preview title | `web_ui.main` and patch constants are regression-tested/reviewed together. |
| Relative image URL cannot be resolved by a crawler | Open Graph and Twitter images use absolute HTTPS production URLs. |
| Old card remains visible after deployment | This is normally third-party cache behavior; the live HTML and versioned image URL can be re-scraped without changing app behavior. |
| PNG accidentally becomes oversized or malformed | Tests require PNG format and exact 512×512 / 1200×630 dimensions. |
| Public-repository scanner rejects binary artifacts | The two intentional, generated-from-SVG PNGs are narrowly allow-listed; other image uploads remain prohibited. |
| Platform ignores one metadata family | Both standard HTML, Open Graph, and Twitter/X metadata are provided. |

## Verification contract

Automated tests in `tests/test_link_preview_metadata.py` verify:

1. the raw Streamlit shell says `Process Control`, not `Streamlit`;
2. standard, Open Graph, and Twitter/X tags are present;
3. production preview URLs are absolute and canonical formatting is stable;
4. copied icon, favicon, and preview bytes match repository assets;
5. a second patch is byte-for-byte idempotent;
6. malformed future Streamlit shells fail closed;
7. both PNGs have the exact intended dimensions and format;
8. the Docker patch runs only after repository assets are copied.

Local evidence recorded before publication:

- full suite: `278 passed`;
- target metadata/public-hygiene suite: `9 passed`;
- patch executed successfully against the real installed Streamlit 1.61.1
  static shell, not only the synthetic test fixture;
- patched shell contained one metadata block, `Process Control`, no default
  `Streamlit` title, an absolute production image URL, and both Open Graph and
  Twitter/X tags;
- copied artifacts decoded as PNG at 512×512, 1200×630, and 512×512 for the
  versioned icon, preview card, and `favicon.png`, respectively.

CI and production checks are still required after the commit reaches `main`.
Render is configured to deploy commits to `main` automatically; do not create a
second manual deployment for the same commit. Wait for the commit-triggered
deployment, then inspect its status and the live raw response.

Release verification must additionally inspect the actual Render response,
without relying on JavaScript:

```bash
curl -fsSL https://msapo-generator.onrender.com/ | grep -E \
  '<title>|og:title|og:image|twitter:card|description'
curl -fsSI https://msapo-generator.onrender.com/process-control-icon-v1.png
curl -fsSI https://msapo-generator.onrender.com/process-control-preview-v1.png
```

Run the first request with ordinary and crawler user agents. The response body
must contain the same metadata in every case. Both image requests must return
HTTP 200 with `Content-Type: image/png`.

## Public-repository and security notes

The assets contain no customer data, employee data, vendor data, email
addresses, contract identifiers, API keys, environment values, or uploaded
documents. The patcher embeds only the already-public production origin and
generic product wording. No Render credential or service-management identifier
is stored in source.

The implementation does not call a third-party image service at runtime and
does not cause receipt or quote content to appear in link metadata. Preview
requests remain ordinary unauthenticated reads of the already-public app shell
and static, repository-owned artwork.

## Non-regression boundaries

- Do not inject quote, receipt, requester, employee, administrator, vendor, or
  facility values into a shared preview image or meta tag. Preview crawlers and
  chat clients may cache and redistribute that data.
- Do not derive the preview from Streamlit session state; crawler requests have
  no user session and must receive a deterministic public card.
- Do not alter the existing application route or add a redirect solely for
  previews. Both humans and crawlers must continue to use the Render root URL.
- Do not add an ENFRA name or logo without explicit brand/legal approval.
- Do not broaden the public-repository binary allow-list by extension or
  directory. Each approved binary must be named explicitly.
- Do not move the patch before `pip install`; it must target the actual
  Streamlit version installed in the final image layer.
- Do not turn a missing shell anchor into a warning. A failed build is safer
  than silently restoring the misleading `Streamlit` preview.

## Change guidance for a future coding agent

- Keep runtime and crawler titles synchronized.
- Keep preview images generic unless the product owner explicitly approves a
  corporate logo/name for public use.
- Do not replace the absolute HTTPS social-image URLs with relative URLs.
- Increment the deployed asset version when changing artwork.
- Do not patch files at container startup; a failed patch should prevent the
  image from building, not fail unpredictably while serving traffic.
- Re-run the full repository suite and the production raw-HTML checks after a
  Streamlit version change.

## Rollback

Remove the Docker `RUN python scripts/patch_streamlit_metadata.py` line and
restore the previous `st.set_page_config` values. This returns crawler behavior
to Streamlit's default without affecting either purchase-order or expense
workflow data. No database or persistent-disk migration is involved.
