"""Offline exact-locator contracts, not native browser acceptance."""
import ast
import inspect
import sys
from types import SimpleNamespace

import pytest

from scripts import qa_warning_routes as qa


@pytest.mark.parametrize('owners,labels,fields,accepted', [
    (1, ('Source date',), 1, True),
    (1, ('Report date', 'Source date'), 1, True),
    (0, ('Source date',), 1, False),
    (2, ('Source date',), 1, False),
    (1, ('Report date',), 1, False),
    (1, ('Source date extra',), 1, False),
    (1, ('Source date', 'Source date'), 1, False),
    (1, ('Source date',), 0, False),
    (1, ('Source date',), 2, False),
])
def test_exact_source_date_refuses_missing_wrong_or_duplicate_owners_and_widgets(
        monkeypatch, owners, labels, fields, accepted):
    events=[]

    class Nodes:
        def __init__(self, count, kind):
            self.count,self.kind=count,kind

        def get_by_test_id(self, testid):
            events.append((self.kind,testid))
            if self.kind=='target owner':
                assert testid=='stDateInput'
                return Widgets(self.count*len(labels),'widgets')
            assert self.kind=='widgets' and testid=='stDateInputField'
            return Nodes(self.count*fields,'native scalar')

        def get_by_role(self, role, *, name, exact):
            assert self.kind=='target owner' and role=='textbox' and exact
            # Observed Streamlit scalar input announces "Select a date.";
            # the visible Source date text labels its containing widget.
            return Nodes(self.count*fields if name=='Select a date.' else 0,'native scalar')

    class Widgets(Nodes):
        def filter(self, *, has):
            # The actual shared helper must use the page-relative exact label,
            # not an owner-prefixed locator inside the relative has selector.
            assert has==('page label','Source date',True)
            return Widgets(owners*labels.count('Source date'),'widgets')

    class Page:
        def locator(self, selector):
            assert selector=='.st-key-report_managed_source_expected'
            # An unrelated source also has a native Source date. It must not
            # compensate for an absent or ambiguous expected source owner.
            return Nodes(owners,'target owner')

        def get_by_text(self, label, *, exact):
            return ('page label',label,exact)

        def get_by_role(self, *args, **kwargs):
            raise AssertionError('Source date is a widget label, not the scalar accessible name.')

    class Expect:
        def __init__(self, locator):self.locator=locator
        def to_have_count(self, count):
            events.append(('count',self.locator.kind,count))
            assert self.locator.count==count

    monkeypatch.setitem(sys.modules,'playwright.sync_api',SimpleNamespace(expect=Expect))
    page=Page();owner=page.locator('.st-key-report_managed_source_expected')
    assignment=next(node for node in ast.walk(ast.parse(inspect.getsource(qa.exercise)))
                    if isinstance(node,ast.Assign) and any(
                        isinstance(target,ast.Name) and target.id=='date_field' for target in node.targets))
    def resolve_actual_driver():
        namespace={'page':page,'owner':owner,'source_date_control':getattr(qa,'source_date_control',None)}
        exec(compile(ast.Module(body=[assignment],type_ignores=[]),qa.__file__,'exec'),namespace)
        control=namespace['date_field']
        Expect(control).to_have_count(1)  # Existing first focus_proof prerequisite.
        return control
    if accepted:
        control=resolve_actual_driver()
        assert control.kind=='native scalar' and control.count==1
        assert events[-1]==('count','native scalar',1)
    else:
        with pytest.raises(AssertionError):resolve_actual_driver()


def test_date_route_keeps_exact_saved_owner_and_original_focus_and_commit_contract():
    source=inspect.getsource(qa.exercise)
    assert "owner=page.locator('.st-key-'+prefix+'_managed_source_'+target['id'])" in source
    assert 'date_field=source_date_control(page,owner)' in source
    assert source.index('date_field=source_date_control(page,owner)') < source.index("jump('source_date_unknown',date_field)")
    assert "date_field.fill('2026-09-03');date_field.press('Tab')" in source
    assert "expect(control).to_have_count(1);expect(control).to_be_focused()" in source
    assert 'to_be_in_viewport(ratio=1)' in source
    assert len(qa.required_cases())==16
    helper=inspect.getsource(qa.source_date_control)
    for bypass in ('.first', '.nth(', 'force=', 'sleep(', 'timeout=', '.evaluate(', '.click('):
        assert bypass not in helper
    calls=[node for node in ast.walk(ast.parse(helper)) if isinstance(node,ast.Call)]
    assert not any(isinstance(call.func,ast.Attribute) and call.func.attr in {'fill','press','focus'} for call in calls)
