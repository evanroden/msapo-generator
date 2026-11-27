from pathlib import Path
from types import SimpleNamespace
import json
import pytest
from scripts import workspace_final_action_observations as observe


def test_receipt_rejects_content_and_unknown_fields(tmp_path):
    path=tmp_path/'receipt.jsonl'
    with pytest.raises(ValueError):observe._append(path,'button_return',label='Private')
    with pytest.raises(ValueError):observe._append(path,'button_return',pressed='Private')
    with pytest.raises(ValueError):observe._append(path,'Private')
    assert not path.exists()


def _install(monkeypatch,tmp_path,generate):
    from app import monthly_report_guided as guided,monthly_report_output_ui as output
    monkeypatch.setattr(observe,'require_synthetic_root',lambda base:None)
    button=lambda label,*a,**kw:label=='Create Word and PDF'
    replace=lambda *a,**kw:None
    monkeypatch.setattr(guided.st,'button',button)
    monkeypatch.setattr(guided,'generate_report',generate)
    monkeypatch.setattr(output,'replace_current_session_pdf_package',replace)
    return guided,output,button,replace


def test_success_observes_actual_returns_and_restores(monkeypatch,tmp_path):
    package=SimpleNamespace(pdf=b'pdf',docx=b'docx')
    generate=lambda *a,**kw:package
    guided,output,button,replace=_install(monkeypatch,tmp_path,generate)
    with observe.observe_final_action(tmp_path):
        assert guided.st.button('Other action') is False
        assert guided.st.button('Create Word and PDF',disabled=False) is True
        assert guided.generate_report(object()) is package
        output.replace_current_session_pdf_package('prefix','scope',package)
    assert guided.st.button is button and guided.generate_report is generate
    assert output.replace_current_session_pdf_package is replace
    rows=[json.loads(line) for line in (tmp_path/'synthetic-final-action-receipts.jsonl').read_text().splitlines()]
    assert [r['event'] for r in rows]==['render_enter','button_return','generation_enter','generation_return','package_replace_enter','package_replace_return','render_return']
    assert rows[1]['pressed'] is True
    assert rows[3]['pdf_bytes']==3 and rows[3]['docx_bytes']==4
    assert 'prefix' not in str(rows) and 'scope' not in str(rows)


def test_generation_error_is_durable_and_does_not_change_exception(monkeypatch,tmp_path):
    error=RuntimeError('Private exception detail must not be logged')
    def generate(*a,**kw):raise error
    guided,output,button,replace=_install(monkeypatch,tmp_path,generate)
    with pytest.raises(RuntimeError) as caught:
        with observe.observe_final_action(tmp_path):guided.generate_report(object())
    assert caught.value is error and guided.generate_report is generate
    raw=(tmp_path/'synthetic-final-action-receipts.jsonl').read_text()
    assert 'generation_error' in raw and 'render_error' in raw and 'Private' not in raw


def test_requires_marked_synthetic_root(tmp_path):
    with pytest.raises(ValueError):
        with observe.observe_final_action(tmp_path):pass
    assert not (tmp_path/'synthetic-final-action-receipts.jsonl').exists()
