"""Explicit human-reviewed immutable ENFRA PDF pages, confined to MBCx.

Neither OCR nor classification guesses authorize output. The review attests to
financial meaning after visual inspection; known vendor totals still veto it.
Source bytes are verified before review/preparation. Other source/field routes
retain their existing policy. This is not an AR arithmetic implementation.
"""
from dataclasses import asdict, dataclass, replace
import hashlib
import json
import re
from app.monthly_report_financial_policy import FinancialScope, SourceFinancialReview, ReviewedFinancialPage

SEMANTICS = 'client_enfra_no_vendor_totals'
FINANCIAL_RECEIPT = 'financial:v1:'
_VENDOR_INVOICE = re.compile(r'\b(?:vendor|supplier|subcontractor)\s+invoice\b', re.I)
_TOTAL_LABEL = re.compile(r'\b(?:total|amount\s+due|balance\s+due)\b', re.I)


def scope_for(profile):
    facilities=tuple((f.key,f.title,f.aliases) for f in profile.facilities)
    return FinancialScope(profile.contract, hashlib.sha256(json.dumps((profile.key,profile.scope_type,facilities),sort_keys=True).encode()).hexdigest())


def page_review_fingerprint(source,number):
    if type(number) is not int or not 1 <= number <= len(source.page_texts):
        raise ValueError('Invalid financial page identity.')
    record=(source.sha256,source.id,number,source.page_texts[number-1],dict(source.captions).get(number,''),source.facility,source.service_date,source.scope_review)
    return hashlib.sha256(json.dumps(record,ensure_ascii=False).encode()).hexdigest()


def known_vendor_total(source,number):
    text = ' '.join((source.page_texts[number-1] + ' ' + dict(source.captions).get(number,'')).split())
    return bool(_VENDOR_INVOICE.search(text) and _TOTAL_LABEL.search(text))



def has_financial_page_review(source, number):
    """Keep stale/stripped financial evidence distinct from generic page review."""
    return (any(item.number == number for item in source.financial_page_reviews)
            or str(dict(source.client_page_reviews).get(number, '')).startswith(FINANCIAL_RECEIPT))

def financial_page_allowed(source,number,profile,destination,*,output_captions=()):
    if destination!='mbcx_report' or profile is None or source.suffix!='.pdf':return False
    from app.monthly_report_content_policy import contains_price,page_fingerprint,page_status
    if type(number) is not int or not 1<=number<=len(source.page_texts):return False
    review=source.financial_source_review
    if (review is None or review.version!=1 or review.source_id!=source.id
        or review.source_sha256!=source.sha256 or review.scope!=scope_for(profile)
        or review.role!='enfra_client_report' or review.audience!='client'):return False
    matches=[p for p in source.financial_page_reviews if p.number==number]
    if len(matches)!=1:return False
    grant=matches[0]
    if (grant.version!=1 or grant.semantics!=SEMANTICS
        or grant.source_review_fingerprint!=review.fingerprint
        or grant.fingerprint!=page_review_fingerprint(source,number)
        or known_vendor_total(source,number)):return False
    # Caption prose has not acquired financial provenance in this slice.
    if contains_price(dict(source.captions).get(number,'')):return False
    for caption in output_captions:
        captions=dict(source.captions);captions[number]=caption
        if contains_price(caption) or known_vendor_total(replace(source,captions=tuple(captions.items())),number):return False
    status,_=page_status(source.page_texts[number-1],unreadable=number in source.needs_vision)
    if status in ('legal','blank','signature'):return False
    return (number in source.selected_pages
        and number not in dict(source.client_page_exclusions)
        and dict(source.client_page_reviews).get(number)==FINANCIAL_RECEIPT+page_fingerprint(source,number))


def review_pages(profile,content,numbers,*,source_confirmed,visual_fingerprints,financial_semantics):
    """Atomic explicit batch review, called only after showing these exact pages."""
    from app import monthly_report_sources as sources
    from app.monthly_report_content_policy import page_fingerprint,contains_price,page_status
    source=content.source
    sources.source_bytes(profile,source)  # verify stored original, not metadata
    numbers=tuple(numbers)
    if (source.suffix!='.pdf' or not numbers or len(set(numbers))!=len(numbers)
        or financial_semantics!=SEMANTICS):raise ValueError('Review the selected PDF pages and their financial meaning.')
    existing=source.financial_source_review
    expected=SourceFinancialReview(source.id,source.sha256,scope_for(profile),'enfra_client_report','client')
    if existing!=expected and not source_confirmed:
        raise ValueError('Confirm this is an ENFRA report intended for the client.')
    visual=dict(visual_fingerprints)
    if len(visual)!=len(visual_fingerprints) or set(visual)!=set(numbers):
        raise ValueError('The visually reviewed page selection changed.')
    # Validate the complete batch before producing any changed source record.
    for number in numbers:
        if visual[number]!=page_review_fingerprint(source,number):raise ValueError('The reviewed page changed.')
        if known_vendor_total(source,number):raise ValueError('A vendor-invoice total cannot be included in the monthly report.')
        if number in dict(source.client_page_exclusions):raise ValueError('A selected page was deliberately excluded. Restore it explicitly in page review first.')
        status,_=page_status(source.page_texts[number-1],unreadable=number in source.needs_vision)
        if status in ('legal','blank','signature') or contains_price(dict(source.captions).get(number,'')):
            raise ValueError('This page or its caption remains blocked by the existing content policy.')
    grants={p.number:p for p in source.financial_page_reviews}
    ordinary=dict(source.client_page_reviews)
    for number in numbers:
        grants[number]=ReviewedFinancialPage(number,visual[number],expected.fingerprint,SEMANTICS)
        ordinary[number]=FINANCIAL_RECEIPT+page_fingerprint(source,number)
    revised=replace(source,financial_source_review=expected,financial_page_reviews=tuple(grants[n] for n in sorted(grants)),
                    selected_pages=tuple(sorted(set(source.selected_pages)|set(numbers))),client_page_reviews=tuple(sorted(ordinary.items())))
    return replace(content,source=revised)




def omitted_retained_target(block):
    return bool(block is not None and block.source == 'Omit' and (
        block.asset_hashes or block.text.strip() or block.rows or block.extra_tables
        or block.org_nodes or block.ai_paragraphs))

def include_reviewed_batch(profile,content,numbers,blocks,assets=None,*,replace_edited=False,**review):
    """Pure batch result: source, incremental additions, in-place renewals.

    Renew uniquely mapped original-page rasters without replacing them. Edited
    artwork changes only with an explicit replacement choice; captions,
    occurrence identities, order and manual prose are never rebuilt or deleted.
    All validation/preparation finishes before the caller applies any result.
    """
    from app import monthly_report_sources as sources, monthly_report_library as library
    from app.monthly_report_section_uploads import prepare_section_pages, included_pages, page_identity
    from app.monthly_report_page_controls import page_asset_index
    from app.monthly_report_asset_instances import asset_instances, with_asset_instances
    from app.monthly_report_asset_review import _source_context_marker, approve_asset
    from app.monthly_report_content_policy import contains_price
    current=blocks.get('mbcx_report')
    if omitted_retained_target(current):
        raise ValueError('Retained MBCx content is deliberately left out. Include that retained block explicitly before adding or re-reviewing pages; nothing changed.')
    revised=review_pages(profile,content,numbers,**review)
    owners=included_pages(blocks)
    renew=[];fresh=[]
    for number in numbers:
        owned=owners.get((content.source.id,number),set())
        if not owned:
            fresh.append(number);continue
        if owned!={'mbcx_report'} or current is None or current.source=='Omit':
            raise ValueError('Review this page in its existing section; omitted content stays omitted.')
        index=page_asset_index(current,content.source.id,number)
        if index is None:raise ValueError('This page has ambiguous picture occurrences. Use its existing picture controls; nothing changed.')
        original=sources.page_image(profile,content,number)
        expected=library.asset_reference(original.data,original.extension)
        retained=current.asset_hashes[index]
        if retained!=expected and not replace_edited:
            raise ValueError(f'Page {number} has edited artwork. Review both pictures and choose replacement in place; its image and caption were kept.')
        # A reference is not a byte check, including unsaved edited images.
        from pathlib import Path
        raw=(assets or {}).get(retained)
        if raw is None:raw=library.read_asset(profile.contract,profile.key,retained)
        if library.asset_reference(raw,Path(retained).suffix.lstrip("."))!=retained:
            raise ValueError('The retained page image failed its integrity check.')
        if retained==expected and raw!=original.data:
            raise ValueError('The retained original-page image failed its integrity check.')
        if retained!=expected:
            library._atomic_write(library._profile_path(profile.contract,profile.key)/'assets'/expected,original.data)
        caption=current.asset_captions[index] if index<len(current.asset_captions) else ''
        caption_context=dict(revised.source.captions);caption_context[number]=caption
        if known_vendor_total(replace(revised.source,captions=tuple(caption_context.items())),number):
            raise ValueError(f'Page {number} and its retained caption identify a vendor-invoice total.')
        if contains_price(caption):raise ValueError(f'Page {number} has an unapproved monetary caption. Correct that caption in its picture controls.')
        renew.append((number,index,expected))
    additions=(prepare_section_pages(profile,(revised,),'mbcx_report',blocks,assets,
        only_pages=frozenset((content.source.id,n) for n in fresh)) if fresh else {})
    replacements={}
    if renew:
        items=list(asset_instances(current));references=list(current.references);hashes=list(current.asset_hashes)
        for number,index,expected in renew:
            pair=(content.source.id,number)
            reference=sources.source_reference(revised.source,number)
            references=[reference if page_identity(old)==pair else old for old in references]
            context=tuple(old for old in items[index].references
                if page_identity(old)!=pair and not old.startswith(f'asset-source-context:v1:{content.source.id}:{number}:'))
            hashes[index]=expected
            items[index]=replace(items[index],asset=expected,references=tuple(sorted(set((*context,reference,_source_context_marker(revised.source,number))))))
        updated=with_asset_instances(replace(current,asset_hashes=tuple(hashes),references=tuple(dict.fromkeys(references))),items)
        for _,index,_ in renew:updated=approve_asset(updated,index)
        replacements[current.key]=updated
    # Enforce final combined budget, counting replacements once rather than as
    # duplicate appended pages. No old asset or original snapshot is removed.
    total=0
    for key,block in {**blocks,**replacements}.items():
        if key in sources.PAGE_DESTINATIONS:
            for ref in block.asset_hashes:
                raw=(assets or {}).get(ref)
                if raw is None:raw=library.read_asset(profile.contract,profile.key,ref)
                total+=len(raw)
    for block in additions.values():
        total+=sum(len(library.read_asset(profile.contract,profile.key,ref)) for ref in block.asset_hashes)
    if total>60*1024*1024:raise ValueError('Reviewed pages exceed the report image budget. Existing pictures were kept.')
    return revised,additions,replacements



def _state_digest(value):
    return hashlib.sha256(json.dumps(asdict(value) if value is not None else None,sort_keys=True,ensure_ascii=False).encode()).hexdigest()



def _section_digest(sections):
    matched=[section for section in sections or () if any(spec.key=='mbcx_report' for spec in section.blocks)]
    if len(matched)!=1 or not matched[0].included:
        raise ValueError('Include the MBCx section explicitly before reviewing financial pages; its retained content is unchanged.')
    return _state_digest(matched[0])

@dataclass(frozen=True)
class FinancialPageBatch:
    token: str
    profile_digest: str
    period_key: str
    editor_scope: str
    section_digest: str
    source_id: str
    source_before: str
    block_before: str
    revised_content: object
    final_block: object


def stage_financial_batch(profile,period,content,numbers,blocks,assets=None,*,editor_scope,sections,**review):
    """Precompute the production merge before any source/cache/block commit."""
    from uuid import uuid4
    from app.monthly_report_setup import merge_report_block
    section_digest=_section_digest(sections)
    revised,additions,replacements=include_reviewed_batch(profile,content,numbers,blocks,assets,**review)
    final=replacements.get('mbcx_report',blocks.get('mbcx_report'))
    if 'mbcx_report' in additions:final=merge_report_block(final,additions['mbcx_report'],None,None)
    if final is None:raise ValueError('No reviewed page change was prepared.')
    return FinancialPageBatch(uuid4().hex,_state_digest(profile),period.key,editor_scope,section_digest,content.source.id,
        content.source.fingerprint,_state_digest(blocks.get('mbcx_report')),revised,final)


def apply_financial_batch(draft,blocks,current_sources,batch,*,editor_scope,consumed=(),retained_sources=()):
    """One pure draft transition; stale/repeated actions change nothing."""
    if (not isinstance(batch,FinancialPageBatch) or batch.token in consumed
        or not editor_scope or batch.editor_scope!=editor_scope
        or batch.profile_digest!=_state_digest(draft.profile) or batch.period_key!=draft.period.key
        or batch.section_digest!=_section_digest(draft.sections)
        or batch.block_before!=_state_digest(blocks.get('mbcx_report'))):
        raise ValueError('The report changed after financial-page review. No pages or reviews were changed.')
    candidates=[source for source in current_sources if source.id==batch.source_id]
    if len(candidates)!=1 or candidates[0].fingerprint!=batch.source_before:
        raise ValueError('The source changed after financial-page review. No pages or reviews were changed.')
    revised_sources=tuple(batch.revised_content.source if source.id==batch.source_id else source for source in current_sources)
    known={source.id for source in revised_sources}
    revised_sources+=tuple(source for source in retained_sources if source.id not in known)
    updated=dict(blocks);updated['mbcx_report']=batch.final_block
    return replace(draft,sources=revised_sources,blocks=tuple(updated.get(block.key,block) for block in draft.blocks)
                   +tuple(block for key,block in updated.items() if key not in {old.key for old in draft.blocks})),updated

def render_reviewed_batch(profile,content,blocks,assets,prefix,*,period,editor_scope,sections):
    """One explicit visual review for a selected immutable-page batch.

    Returns (handled, revised_content, additions). Caller persists only after the
    entire preparation succeeds; failed last pages cannot partially approve.
    """
    import streamlit as st
    from app import monthly_report_sources as sources
    from app.monthly_report_section_uploads import included_pages,prepare_section_pages
    from app.monthly_report_source_preview import source_thumbnail_uri
    if content.source.suffix!='.pdf':return False,content,{}
    key=prefix+'_financial_'+content.source.id
    if not st.checkbox('Review client-facing ENFRA financial pages',key=key+'_open'):
        return False,content,{}
    source=content.source
    try:
        section_digest=_section_digest(sections)
    except ValueError as exc:
        st.warning(str(exc));return True,content,{}
    if omitted_retained_target(blocks.get('mbcx_report')):
        st.warning('Retained MBCx content is left out. Include that retained block explicitly before adding or re-reviewing pages. Its pictures, captions and notes are unchanged.')
        return True,content,{}
    st.caption('Amounts in ENFRA client reports may be included. Vendor-invoice totals must stay out. This review does not approve editable financial text or tables.')
    expected=SourceFinancialReview(source.id,source.sha256,scope_for(profile),'enfra_client_report','client')
    confirmed=(source.financial_source_review==expected)
    if not confirmed:
        confirmed=st.checkbox('This is an ENFRA report intended for the client',key=key+'_source_'+expected.fingerprint)
    else:st.caption('Client-facing ENFRA source confirmed.')
    owners=included_pages(blocks)
    excluded=dict(source.client_page_exclusions)
    available=tuple(n for n in sources.image_numbers(content) if n not in excluded
                    and (not owners.get((source.id,n)) or owners[(source.id,n)]=={'mbcx_report'}))
    if not available:
        st.caption('No eligible pages to review. Deliberate exclusions and other sections are unchanged.')
        return True,content,{}
    pages=tuple(st.multiselect('Pages to review together',available,key=key+'_pages',max_selections=4,
        format_func=lambda n:f'Page {n}' + (' · already included' if (source.id,n) in owners else ' · new')))
    receipts=[];failure=False;edited=[]
    for number in pages:
        try:
            image=sources.page_image(profile,content,number,preview=True)
            st.image(source_thumbnail_uri(image),caption=f'Page {number}',width=650)
            receipts.append((number,page_review_fingerprint(source,number)))
            if (source.id,number) in owners:
                from app.monthly_report_page_controls import page_asset_index
                block=blocks.get('mbcx_report');index=page_asset_index(block,source.id,number)
                if index is not None:
                    st.caption('Retained caption: ' + (block.asset_captions[index] if index<len(block.asset_captions) else ''))
                    from app import monthly_report_library as library
                    original=sources.page_image(profile,content,number)
                    if block.asset_hashes[index]!=library.asset_reference(original.data,original.extension):
                        ref=block.asset_hashes[index]
                        retained=(assets or {}).get(ref)
                        if retained is None:retained=library.read_asset(profile.contract,profile.key,ref)
                        st.image(retained,caption=f'Current included picture for page {number} — will be replaced only if you choose',width=650)
                        edited.append(number)
            if known_vendor_total(source,number):
                st.warning(f'Page {number} identifies a vendor-invoice total and cannot be included.')
                failure=True
        except (ValueError,OSError) as exc:
            st.error(str(exc));failure=True
    stamp=hashlib.sha256(json.dumps((section_digest,editor_scope,period.key,_state_digest(profile),expected.fingerprint,receipts,blocks.get('mbcx_report').fingerprint if blocks.get('mbcx_report') else ''),sort_keys=True).encode()).hexdigest()
    replacement_confirmed=(st.checkbox('Replace the edited pictures shown above with these reviewed original pages; keep their captions and positions',key=key+'_replace_'+stamp) if edited else False)
    checked=st.checkbox('I reviewed these pages: their amounts are client-facing ENFRA content, with no vendor-invoice totals',key=key+'_visual_'+stamp,disabled=not pages or failure)
    if st.button('Include reviewed financial pages',key=key+'_include_'+stamp,disabled=not pages or not confirmed or not checked or failure or bool(edited and not replacement_confirmed)):
        try:
            batch=stage_financial_batch(profile,period,content,pages,blocks,assets,editor_scope=editor_scope,sections=sections,replace_edited=replacement_confirmed,source_confirmed=confirmed,
                visual_fingerprints=tuple(receipts),financial_semantics=SEMANTICS)
        except (ValueError,OSError) as exc:
            st.error(str(exc));st.caption('No selected pages or reviews were accepted. Your report is unchanged.')
        else:
            return True,content,batch
    return True,content,{}
