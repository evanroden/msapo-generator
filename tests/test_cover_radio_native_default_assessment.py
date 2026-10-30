"""Native default agrees with staged choice; not a browser-race reproduction."""
import pytest
from tests.test_monthly_report_template_fallback import setup,choice,plan_key
from tests.test_monthly_report_starting_review_recovery import continue_button

def radio(app):
    return next(r for r in app.radio if r.key.endswith('_section_cover_action'))

def assert_native(app, action):
    r=radio(app)
    assert r.value == action
    assert r.proto.options[r.proto.default] == r._widget_state.string_value
    return r.proto.id

def test_template_and_cancel_native_default_and_stable_identity(monkeypatch,tmp_path):
    app,_=setup(monkeypatch,tmp_path)
    before=assert_native(app,'Keep and review')
    choice(app).click().run()
    selected=assert_native(app,'Leave this section out')
    assert selected != before
    app.run()
    assert assert_native(app,'Leave this section out')==selected
    next(b for b in app.button if b.label=='Keep uploaded report design instead').click().run()
    assert assert_native(app,'Keep and review') not in {before, selected}
    assert continue_button(app).disabled

@pytest.mark.parametrize('action',['Keep and review','Edit text or change pictures','Leave this section out'])
def test_three_explicit_actions_native_defaults(monkeypatch,tmp_path,action):
    app,_=setup(monkeypatch,tmp_path)
    choice(app).click().run()
    before=radio(app).proto.id
    radio(app).set_value(action).run()
    assert assert_native(app,action)==before
    assert bool(app.session_state[plan_key(app)]['cover']['omit']) == (action=='Leave this section out')
    if action!='Leave this section out':assert continue_button(app).disabled

def test_invalid_cover_action_does_not_authorize_omit(monkeypatch,tmp_path):
    app,_=setup(monkeypatch,tmp_path)
    choice(app).click().run()
    states=app._tree.get_widget_states()
    target=next(w for w in states.widgets if w.id==radio(app).proto.id)
    target.string_value='stale unknown synthetic cover label'
    app._run(states)
    assert assert_native(app,'Keep and review')
    assert not app.session_state[plan_key(app)]['cover']['omit']
    assert continue_button(app).disabled


def test_display_labels_deserialize_to_internal_actions_across_template_transition(monkeypatch,tmp_path):
    app,_=setup(monkeypatch,tmp_path)
    def mapping():
        r=radio(app)
        metadata=app.session_state._state._new_widget_state.widget_metadata[r.proto.id]
        return {label:metadata.deserializer(label) for label in r.proto.options}
    before=mapping()
    assert before['Leave imported cover artwork out']=='Leave this section out'
    choice(app).click().run()
    selected=mapping()
    assert selected['Use selected ENFRA template']=='Leave this section out'
    app.run()
    assert mapping()==selected
    next(b for b in app.button if b.label=='Keep uploaded report design instead').click().run()
    assert mapping()==before
