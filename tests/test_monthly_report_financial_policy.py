"""Synthetic policy foundation; no existing output gate is relaxed."""
from dataclasses import asdict, replace
import hashlib
import importlib
import pytest

SHA = hashlib.sha256(b'synthetic source').hexdigest()
CONTENT = hashlib.sha256(b'Amount $125').hexdigest()


def fixture():
    p = importlib.import_module('app.monthly_report_financial_policy')
    scope = p.FinancialScope('contract-a', 'site-a')
    review = p.SourceFinancialReview('source-a', SHA, scope, 'contract', 'client', 1)
    evidence = p.MonetaryEvidence('source-a', review.fingerprint, 'table:1:row:1:amount', CONTENT, 'amount')
    return p, scope, review, evidence


def evaluate(p, base_scope, review, base_evidence, **kwargs):
    args = dict(purpose='monthly_export', scope=base_scope, locator=base_evidence.locator,
                content_sha256=CONTENT, evidence=(base_evidence,), reviews=(review,),
                current_sources=(('source-a', SHA),))
    args.update(kwargs)
    return p.financial_permission(**args)


@pytest.mark.parametrize('role,audience', [('contract','client'), ('contract','internal'), ('enfra_client_report','client')])
def test_permitted_supported_sources(role, audience):
    p,s,r,e = fixture(); r = replace(r,role=role,audience=audience); e=replace(e,review_fingerprint=r.fingerprint)
    assert evaluate(p,s,r,e).allowed


@pytest.mark.parametrize('role,audience,kind', [
    ('vendor_invoice','client','amount'), ('vendor_invoice','client','vendor_invoice_total'),
    ('unknown','client','amount'), ('enfra_client_report','internal','amount'),
    ('enfra_client_report','unknown','amount'), ('contract','client','unknown'),
    ('enfra_client_report','client','vendor_invoice_total'), ('contract','client','vendor_invoice_total'),
])
def test_denied_sources_and_semantics(role,audience,kind):
    p,s,r,e=fixture();r=replace(r,role=role,audience=audience);e=replace(e,review_fingerprint=r.fingerprint,kind=kind)
    assert not evaluate(p,s,r,e).allowed


@pytest.mark.parametrize('change', ['bytes','content','site','contract','review','locator','missing','mixed','duplicate','version','malformed','copy'])
def test_stale_unknown_or_ambiguous_evidence_is_denied(change):
    p,s,r,e=fixture();kw={}
    if change=='bytes':kw['current_sources']=(('source-a','b'*64),)
    if change=='content':kw['content_sha256']='c'*64
    if change=='site':kw['scope']=replace(s,site_id='site-b')
    if change=='contract':kw['scope']=replace(s,contract_id='contract-b')
    if change=='review':r=replace(r,audience='internal')
    if change=='locator':kw['locator']='table:2:row:1:amount'
    if change=='missing':kw['evidence']=()
    if change=='mixed':kw['evidence']=(e,replace(e,kind='vendor_invoice_total'))
    if change=='duplicate':kw['reviews']=(r,r)
    if change=='version':r=replace(r,version=99);e=replace(e,review_fingerprint=r.fingerprint)
    if change=='malformed':kw['content_sha256']='not-a-digest'
    if change=='copy':kw['locator']='paragraph:copied'
    assert not evaluate(p,s,r,e,**kw).allowed


def test_display_is_not_export_authorization():
    p,s,r,e=fixture();r=replace(r,role='vendor_invoice');e=replace(e,kind='vendor_invoice_total')
    assert evaluate(p,s,r,e,purpose='internal_display',evidence=()).allowed
    assert not evaluate(p,s,r,e).allowed
    assert not evaluate(p,s,r,e,purpose='expense_export').allowed


def test_decision_preserves_input_data():
    p,s,r,e=fixture();before=(asdict(r),asdict(e))
    evaluate(p,s,r,e)
    assert before==(asdict(r),asdict(e))
