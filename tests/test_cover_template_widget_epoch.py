"""Late pre-transition wire payloads cannot undo explicit cover-template choices."""
from copy import deepcopy
from tests.test_monthly_report_template_fallback import setup, choice, plan_key
from tests.test_monthly_report_starting_review_recovery import continue_button
from tests.test_cover_radio_native_default_assessment import radio


def deliver_old_radio(app, old):
    states = app._tree.get_widget_states()
    for widget in states.widgets:
        if widget.id == old.id:
            widget.CopyFrom(old)
            break
    else:
        states.widgets.add().CopyFrom(old)
    app._run(states)
    assert not app.exception


def test_late_pre_choice_radio_preserves_template_and_body(monkeypatch, tmp_path):
    app, source = setup(monkeypatch, tmp_path)
    original = source.read_bytes()
    plans = app.session_state[plan_key(app)]
    body = plans['activity']
    body['texts'][body['selected'][0]] = 'September 2026 pending body correction.'
    preserved = deepcopy(body)
    old = deepcopy(radio(app)._widget_state)
    choice(app).click().run()
    deliver_old_radio(app, old)
    assert app.session_state[plan_key(app)]['cover']['omit']
    assert app.session_state[plan_key(app)]['activity'] == preserved
    assert not continue_button(app).disabled
    continue_button(app).click().run()
    assert not app.exception and not app.error
    assert source.read_bytes() == original


def test_repeated_choose_cancel_retires_only_cover_action(monkeypatch, tmp_path):
    app, _ = setup(monkeypatch, tmp_path)
    body = deepcopy(app.session_state[plan_key(app)]['activity'])
    seen = {radio(app).proto.id}
    for _ in range(3):
        before = deepcopy(radio(app)._widget_state)
        choice(app).click().run()
        selected = deepcopy(radio(app)._widget_state)
        assert selected.id not in seen
        seen.add(selected.id)
        deliver_old_radio(app, before)
        assert app.session_state[plan_key(app)]['cover']['omit']
        next(b for b in app.button if b.label == 'Keep uploaded report design instead').click().run()
        assert radio(app).proto.id not in seen
        seen.add(radio(app).proto.id)
        deliver_old_radio(app, selected)
        assert not app.session_state[plan_key(app)]['cover']['omit']
        assert continue_button(app).disabled
        app.run()  # ordinary re-entry retains this transition's identity
        assert radio(app).proto.id in seen
        assert app.session_state[plan_key(app)]['activity'] == body


def test_fresh_user_choice_after_transition_is_not_overridden(monkeypatch, tmp_path):
    app, _ = setup(monkeypatch, tmp_path)
    choice(app).click().run()
    identity = radio(app).proto.id
    for action in ('Keep and review', 'Edit text or change pictures', 'Leave this section out'):
        radio(app).set_value(action).run()
        assert radio(app).proto.id == identity
        assert radio(app).value == action
        assert app.session_state[plan_key(app)]['cover']['omit'] == (action == 'Leave this section out')
        assert continue_button(app).disabled == (action != 'Leave this section out')
