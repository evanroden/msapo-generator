"""
Entry point: launch the Streamlit web UI.

Usage:
    streamlit run run_web.py

Both workflows live behind this one file. app.web_ui.main renders the
purchase-order flow and dispatches to app.expense_ui for the expense flow, so
this is the ONLY entry point -- pages/ contains a redirect notice, not a second
app. The Dockerfile CMD and every test that drives the UI
(AppTest.from_file(ROOT / "run_web.py")) name this path literally, so renaming it
breaks the container start, the tests, and any bookmark, none of which reference
it through an import.

The `if __name__ == "__main__"` guard is NOT what Streamlit uses. Streamlit
execs this module with __name__ == "__main__" on every rerun, so main() is called
each time -- but the guard also keeps `import run_web` (which the metadata patch
script and some tooling do) from rendering a UI as an import side effect.
"""

from app.web_ui import main

if __name__ == "__main__":
    main()
