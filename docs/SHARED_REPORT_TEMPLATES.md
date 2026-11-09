# Shared report templates

The monthly tool has a separate **Shared report templates for agents** shelf on
the [shared testing page](https://msapo-generator.onrender.com/?workflow=monthly&monthly_qa=fixtures).
It accepts individual Word `.docx` templates up to **512 MiB** and preserves the
exact uploaded bytes and first filename. Anyone who can access the existing
shared testing page can retrieve them without a login. Template storage never
changes an active report, a saved report version, the company master, or an
AUTH01/02/03 scenario.

## Upload and retrieve

1. Open **Shared report templates for agents**.
2. Choose **Word report template**, then **Save shared report template**.
3. Select the filename in **Stored report template**. Record its complete
   SHA-256 and exact byte length privately for independent verification.
4. In a separate browser session, select that same stored template and choose
   **Prepare verified template download**, then **Download unchanged report template**.
5. Compare the downloaded bytes against the independently recorded original
   checksum and length. A catalog listing alone is not a successful download.

An external agent with this repository, Python, and Playwright can retrieve a
stored template through the same interface:

```bash
python -m scripts.qa_fetch_render_archive \
  --archive-kind templates \
  --archive-sha256 <independently-recorded-full-sha256> \
  --archive-size <exact-original-byte-length> \
  --output ./report-template.docx
```

The optional `--bundle-prefix` selects a visible 12-character prefix or full
32-character stored ID. The command verifies the exact downloaded bytes and
the served application revision before and after retrieval. It refuses to
overwrite an existing output. A template becomes available to agents only
after its upload succeeds on the served version containing this feature.

## Storage and limits

Originals and their receipts live in `_enfra_shared_report_templates_v1` under
the existing Render data root. They use the existing descriptor-safe atomic
storage engine, private file permissions, read-time SHA-256 verification, and
an independent **768 MiB** aggregate shelf budget. Insufficient disk space or a
full shelf refuses the new upload while retaining every existing original.
This does not provision or enlarge the Render disk. Test reset does not delete
the shelf. Identical bytes uploaded again return the existing original receipt.

The server upload ceiling is **512 MiB**, and this template uploader explicitly
uses that limit. Other uploaders retain their purpose-specific limits. In
particular, storage is not parsing: the existing report importer, native-art
inspection, AUTH fixtures, source archives and synthetic evidence keep their
own bounds. A large stored template can therefore be downloaded for reference
even when a report import or layout inspection cannot process it.

The DOCX ZIP container is checked for complete required members, CRC integrity,
safe paths, duplicate names, unsupported encryption/compression, bounded member
count and at most 1 GiB of expanded data. No members are extracted or parsed as
report content. This is not a claim of layout fidelity, source correctness,
macro scanning, or importer readiness.

Only receipt metadata is read during ordinary catalog renders. Original bytes
are read on explicit preparation and reverified on the actual download. The
uploader is remounted after successful storage to release the selected upload.
Keep genuine originals, filenames, hashes and download receipts out of public
Git, GitHub issues, CI output and artifacts. Use invented files for automated
checks; store genuine references through the runtime catalog.
