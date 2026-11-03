"""Snapshot-bound AI paragraph destinations; navigation is never fact approval."""
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from app.monthly_report_correction_targets import report_identity


def digest(value):
    return sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class ParagraphTarget:
    report: str
    block_key: str
    block_revision: str
    ordinal: int
    paragraph_revision: str
    reason: str
    facts: tuple
    fact_id: str = ''
    source_id: str = ''
    page: int = 0

    @property
    def token(self):
        return digest(asdict(self))


def fact_bindings(draft,paragraph):
    result=[]
    for identity in paragraph.fact_ids:
        matches=[(source,fact) for source in draft.sources for fact in source.facts if fact.id==identity]
        if not matches:
            result.append((identity,'','','','',0))
        for source,fact in matches:
            result.append((identity,source.id,source.sha256,source.fingerprint,digest(asdict(fact)),fact.page))
    return tuple(result)


def paragraph_target(draft,block,ordinal,reason,*,fact_id='',source_id='',page=0):
    paragraph=block.ai_paragraphs[ordinal]
    return ParagraphTarget(report_identity(draft),block.key,block.fingerprint,ordinal,
        digest(asdict(paragraph)),reason,fact_bindings(draft,paragraph),fact_id,source_id,page)


def resolve_paragraph(draft,target):
    from app.monthly_report_model import used_block_keys
    if not isinstance(target,ParagraphTarget) or target.report!=report_identity(draft):
        return None
    if target.reason not in ('number','evidence','date','review'):
        return None
    if len({s.id for s in draft.sources})!=len(draft.sources):
        return None
    blocks=[b for b in draft.blocks if b.key==target.block_key]
    if len(blocks)!=1 or target.block_key not in used_block_keys(draft):
        return None
    block=blocks[0]
    if (block.source=='Omit' or block.fingerprint!=target.block_revision
            or type(target.ordinal) is not int or not 0<=target.ordinal<len(block.ai_paragraphs)):
        return None
    paragraph=block.ai_paragraphs[target.ordinal]
    # Equal prose/facts are not a persistent occurrence identity. Do not guess
    # which copy survived a legacy reorder in a schema without paragraph IDs.
    if sum(p==paragraph for p in block.ai_paragraphs)!=1:
        return None
    if (digest(asdict(paragraph))!=target.paragraph_revision
            or fact_bindings(draft,paragraph)!=target.facts):
        return None
    for identity in paragraph.fact_ids:
        facts=[(s,f) for s in draft.sources for f in s.facts if f.id==identity]
        if len(facts)>1 or any(f.source_id!=s.id for s,f in facts):
            return None
    if target.reason=='date':
        matches=[(s,f) for s in draft.sources for f in s.facts
                 if f.id==target.fact_id and s.id==target.source_id and f.page==target.page]
        if (len(matches)!=1 or target.fact_id not in paragraph.fact_ids
                or type(target.page) is not int or not 1<=target.page<=len(matches[0][0].page_texts)):
            return None
        from app.monthly_report_ai import fact_date_problems
        if not fact_date_problems((matches[0][1],),draft.sources):
            return None
    return block,paragraph


def unsupported_number_indexes(block,sources):
    """Use numeric evidence validation, not a displayed warning's wording."""
    from app.monthly_report_ai import numbers,fact_numbers
    result=[]
    for index,paragraph in enumerate(block.ai_paragraphs):
        cited=[]
        for identity in paragraph.fact_ids:
            matches=[fact for source in sources for fact in source.facts if fact.id==identity]
            if len(matches)!=1:
                break
            cited.append(matches[0])
        else:
            if cited and numbers(paragraph.text)-fact_numbers(cited):
                result.append(index)
    return tuple(result)
