from dataclasses import replace
from streamlit.testing.v1 import AppTest
from app import monthly_report_org_chart_defaults as charts
from test_monthly_report_org_chart_defaults import scopes, fresh, picture, with_chart, publish, chart

SCRIPT='''
from dataclasses import replace
import streamlit as st
from app.monthly_report_org_chart_defaults_ui import render_chart_defaults
draft=st.session_state['draft']
block=next(b for b in draft.blocks if b.key=='org_chart')
block,explicit=render_chart_defaults(draft,block,st.session_state['assets'],'test')
st.session_state['draft']=replace(draft,blocks=tuple(block if b.key=='org_chart' else b for b in draft.blocks))
st.session_state['explicit']=explicit
'''

def start(d,a):
    app=AppTest.from_string(SCRIPT,default_timeout=20)
    app.session_state['draft']=d;app.session_state['assets']=a
    return app.run()
def button(app,label):return next(b for b in app.button if b.label==label)

def test_publication_requires_consent_and_neutral_rerun_never_publishes(scopes):
    a1,_,_,_=scopes;b,a=picture('red');d=with_chart(fresh(a1),b);app=start(d,a)
    assert not app.exception and charts.load_defaults(a1.contract).revision==0
    assert button(app,'Publish chart default').disabled
    app.checkbox[0].check().run();button(app,'Publish chart default').click().run()
    assert not app.exception and charts.load_defaults(a1.contract).revision==1
    assert app.session_state['draft']==d
    before=(charts._path(a1.contract)/'manifest.json').read_bytes()
    app.run();assert (charts._path(a1.contract)/'manifest.json').read_bytes()==before


def test_stale_scope_click_cannot_publish_to_new_contract(scopes):
    a1,_,b1,_=scopes;b,a=picture('red');d=with_chart(fresh(a1),b);app=start(d,a)
    app.checkbox[0].check().run();button(app,'Publish chart default').click()
    app.session_state['draft']=replace(d,profile=b1)
    app.run()
    assert not app.exception and any('changed' in w.value for w in app.warning)
    assert charts.load_defaults(a1.contract).revision==charts.load_defaults(b1.contract).revision==0


def test_explicit_use_reincludes_only_chart_and_never_publishes(scopes):
    a1,_,_,_=scopes;_,b,_=publish(a1)
    d=with_chart(fresh(a1),replace(b,source='Omit',text='Keep note'));app=start(d,{})
    button(app,'Use saved chart in this report').click().run()
    assert not app.exception and app.session_state['explicit']
    assert chart(app.session_state['draft']).text=='Keep note'
    assert chart(app.session_state['draft']).source=='This month'
    assert charts.load_defaults(a1.contract).revision==1

WRAPPER='''
from dataclasses import replace
import streamlit as st
from app.monthly_report_organization_ui import render_organization
from app.monthly_report_ui import _field
from app.monthly_report_model import BlockSpec
current=st.session_state['draft']
blocks={b.key:b for b in current.blocks}
updated=render_organization(current,blocks,{'org_chart':BlockSpec('org_chart','image_page')},'test',st.session_state['assets'],_field,lambda spec,block:block,show_preview=False)
st.session_state['draft']=replace(current,blocks=tuple(updated.values()))
'''

def test_real_chart_editor_adoption_survives_rerun_close_reopen_and_publish(scopes):
    from app.monthly_report_model import ResolvedBlock,OrgChartNode
    from app import monthly_report_library as library
    a1,_,_,_=scopes
    old=ResolvedBlock('org_chart','This month',org_nodes=(OrgChartNode('lead','Synthetic Old','Lead'),))
    new=replace(old,org_nodes=(OrgChartNode('lead','Synthetic New','Lead'),))
    d=with_chart(fresh(a1),new)
    charts.save_default(d,new,{},scope='contract',expected_revision=0,expected_fingerprint=new.fingerprint,confirmed=True)
    d=with_chart(d,old)
    app=AppTest.from_string(WRAPPER,default_timeout=20)
    app.session_state['draft']=d;app.session_state['assets']={};app.run()
    button(app,'Edit chart').click().run()
    assert next(x for x in app.text_input if x.label=='Name').value=='Synthetic Old'
    button(app,'Use saved chart in this report').click().run()
    assert chart(app.session_state['draft']).org_nodes==new.org_nodes
    app.run()
    assert not app.exception
    assert chart(app.session_state['draft']).org_nodes==new.org_nodes
    assert next(x for x in app.text_input if x.label=='Name').value=='Synthetic New'
    button(app,'Done').click().run();button(app,'Edit chart').click().run()
    assert chart(app.session_state['draft']).org_nodes==new.org_nodes
    next(x for x in app.checkbox if x.label.startswith('Make this reviewed')).check().run()
    button(app,'Publish chart default').click().run();app.run()
    assert not app.exception
    assert charts.selected_default(a1,charts.load_defaults(a1.contract)).block.org_nodes==new.org_nodes
    assert chart(app.session_state['draft']).org_nodes==new.org_nodes
    assert tuple(b for b in app.session_state['draft'].blocks if b.key!='org_chart')==tuple(b for b in d.blocks if b.key!='org_chart')
