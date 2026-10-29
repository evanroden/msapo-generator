"""Explicit publication and reuse beside the existing chart editor."""
from dataclasses import asdict, replace
import streamlit as st
from app import monthly_report_org_chart_defaults as charts
from app.monthly_report_editor import _signature
from app.monthly_report_ui_text import literal


def _queue(key, request):
    st.session_state[key]=request


def render_chart_defaults(draft,block,assets,prefix):
    from app.monthly_report_guided import _rich_text_scope
    scope=_signature((asdict(draft.profile),draft.period.key,draft.prepared_by,_rich_text_scope(prefix)))
    root=prefix+'_chart_defaults_'+scope
    request_key=prefix+'_chart_defaults_request'
    explicit=False
    try:
        state=charts.load_defaults(draft.profile.contract)
        request=st.session_state.pop(request_key,None)
        if request:
            if request.get('scope')!=scope or request.get('fingerprint')!=block.fingerprint:
                raise ValueError('This report or chart changed. Review it before trying again.')
            if request['action']=='use':
                block=charts.use_default(draft,block,assets,expected_revision=request['revision'],expected_fingerprint=request['fingerprint'])
                explicit=True
                st.success('Saved chart applied to this report only.')
            elif request['action']=='save':
                state=charts.save_default(draft,block,assets,scope=request['target'],expected_revision=request['revision'],expected_fingerprint=request['fingerprint'],confirmed=True)
                st.success('Chart saved for future reports. Existing reports are unchanged.')
            else:
                raise ValueError('Review the chart action again.')
    except (ValueError,OSError) as exc:
        st.warning(literal(exc))
        return block,explicit
    with st.expander('Saved charts for future reports'):
        st.caption('Contract: '+literal(draft.profile.contract)+'. Publishing is separate from saving this report.')
        item=charts.selected_default(draft.profile,state)
        if item:
            st.caption(('Site override' if item.site_key else 'Contract default')+f' · saved version {state.revision}')
        else:
            st.caption('No saved chart for this scope.')
        receipt={'scope':scope,'revision':state.revision,'fingerprint':block.fingerprint}
        token=_signature(receipt)
        if item:
            st.button('Use saved chart in this report',key=root+'_use_'+token,
                on_click=_queue,args=(request_key,dict(receipt,action='use')))
        options=['contract']+(['site'] if len(draft.profile.facilities)==1 else [])
        target=st.radio('Publish for',options,format_func=lambda v:'All sites in this contract' if v=='contract' else 'This site only',key=root+'_target')
        confirm=st.checkbox('Make this reviewed chart available to future reports in this scope',key=root+'_confirm_'+token+'_'+target)
        checked=charts.refresh_asset_source_context(block,draft.sources)
        st.button('Publish chart default',key=root+'_save_'+token+'_'+target,
            disabled=not confirm or draft.synthetic or not charts.eligible(checked) or not charts.source_pages_allowed(checked,draft.sources,draft.profile),
            on_click=_queue,args=(request_key,dict(receipt,action='save',target=target)))
    return block,explicit
