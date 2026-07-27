from pathlib import Path

path = Path("scripts/apply_workflow_correctness.py")
text = path.read_text(encoding="utf-8")

start = text.index("def patch_quote_analyzer() -> None:")
end = text.index("\ndef cleanup_scaffold() -> None:", start)

replacement = '''def patch_quote_analyzer() -> None:
    path = "app/quote_analyzer.py"

    replace_once(
        path,
        "working for a " + "\\\\\\n" + "healthcare system.",
        "supporting " + "\\\\\\n" + "multiple facilities-management contracts.",
    )

    replace_once(
        path,
        """   - Unity Hospital, 1555 Long Pond Rd, Rochester, NY 14626
   - St. Mary's Medical Campus, 89 Genesee St, Rochester, NY 14611""",
        """   - Unity Hospital, 1555 Long Pond Rd, Rochester, NY 14626
   - Unity Specialty Hospital, 89 Genesee St, Rochester, NY 14611
   - St. Mary's Medical Campus, 89 Genesee St, Rochester, NY 14611""",
    )

    replace_once(
        path,
        """   - Massena Hospital, 1 Hospital Dr, Massena, NY 13662
   - Clifton Springs Hospital & Clinic, 2 Coulter Rd, Clifton Springs, NY 14432
   If none match,""",
        """   - Massena Hospital, 1 Hospital Dr, Massena, NY 13662
   If none match,""",
    )
'''

text = text[:start] + replacement + text[end:]
text = text.replace('re.sub(r"[^0-9.\\-]", "", value)', 're.sub(r"[^0-9.-]", "", value)')
text = text.replace(
    '    Path(".github/workflows/apply-workflow-correctness.yml").unlink(missing_ok=True)\n',
    '    Path(".github/workflows/apply-workflow-correctness.yml").unlink(missing_ok=True)\n'
    '    Path("scripts/fix_patch_driver.py").unlink(missing_ok=True)\n'
    '    Path("patch-output.txt").unlink(missing_ok=True)\n',
)
path.write_text(text, encoding="utf-8")
