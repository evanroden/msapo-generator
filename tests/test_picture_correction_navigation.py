"""Node contracts are not a substitute for hosted native pointer/keyboard QA."""
from pathlib import Path
import subprocess


def test_picture_correction_navigation_contract():
    subprocess.run(['node', '--test', 'tests/picture_correction_navigation_test.cjs'],
                   cwd=Path(__file__).resolve().parents[1], check=True, capture_output=True, text=True)


def test_page_navigation_request_contract():
    subprocess.run(['node', '--test', 'tests/page_navigation_request_test.cjs'],
                   cwd=Path(__file__).resolve().parents[1], check=True, capture_output=True, text=True)
