from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Expected one match in {path}, found {count}")
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "app/web_ui.py",
    "from app import memory\n",
    "from app import memory\nfrom app.access_control import require_access\n",
)

replace_once(
    "app/web_ui.py",
    '''    st.set_page_config(
        page_title="Email Process Control",
        page_icon="📮",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)''',
    '''    st.set_page_config(
        page_title="Email Process Control",
        page_icon="📮",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    require_access()
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)''',
)

Path("scripts/apply_access_gate.py").unlink(missing_ok=True)
Path(".github/workflows/apply-access-gate.yml").unlink(missing_ok=True)
