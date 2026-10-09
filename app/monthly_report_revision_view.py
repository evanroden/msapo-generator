"""One final revision view for inspection and passive report rendering.

Only disposable XML is changed. Top-level paragraph/table anchors stay stable;
structural revisions that would require new anchors are rejected explicitly.
"""
from dataclasses import dataclass


VERSION = 1
W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
W14 = '{http://schemas.microsoft.com/office/word/2010/wordml}'
COMMENT_TAGS = {W + name for name in ('commentRangeStart', 'commentRangeEnd', 'commentReference', 'annotationRef')}
DELETE_TAGS = {W + name for name in ('del', 'moveFrom', 'delText', 'delInstrText')} | {W14 + 'conflictDel'}
ACCEPT_TAGS = {W + name for name in ('ins', 'moveTo')} | {W14 + 'conflictIns'}
HISTORY_TAGS = {W + name for name in (
    'rPrChange', 'pPrChange', 'sectPrChange', 'tblPrChange', 'tblPrExChange',
    'trPrChange', 'tcPrChange', 'tblGridChange', 'numberingChange', 'cellIns',
    'moveFromRangeStart', 'moveFromRangeEnd', 'moveToRangeStart', 'moveToRangeEnd',
    'customXmlInsRangeStart', 'customXmlInsRangeEnd', 'customXmlDelRangeStart', 'customXmlDelRangeEnd',
    'customXmlMoveFromRangeStart', 'customXmlMoveFromRangeEnd', 'customXmlMoveToRangeStart', 'customXmlMoveToRangeEnd',
    'trackRevisions', 'revisionView',
)}
STRUCTURE_MESSAGE = (
    'This report contains tracked paragraph or table-structure changes that cannot be mapped safely. '
    'Accept or reject those structural changes in Word, save a copy, and upload that copy. '
    'The original and saved report versions were not changed.'
)


@dataclass(frozen=True)
class RevisionView:
    revisions: int = 0
    comments: int = 0


def current_view(root):
    """Accept inline changes and deleted rows; remove old review annotations.

    Works with both ElementTree (streaming inspection) and lxml (native clone).
    Deleting a paragraph *mark* is not deleting its text; do not conflate them.
    Likewise cell-deletion/merge changes need explicit grid reconciliation.
    """
    revisions = comments = 0

    def visit(node, parent_tag=None):
        nonlocal revisions, comments
        # This check runs before removing any property marker that proves the
        # structural operation. A paragraph's current text must never disappear.
        if node.tag == W + 'p':
            mark = node.find(W + 'pPr/' + W + 'rPr')
            if mark is not None and any(child.tag in (W + 'del', W + 'moveFrom') for child in mark):
                raise ValueError(STRUCTURE_MESSAGE)
        if node.tag in (W + 'cellDel', W + 'cellMerge'):
            raise ValueError(STRUCTURE_MESSAGE)
        if node.tag in DELETE_TAGS | ACCEPT_TAGS and any(child.tag in (W + 'p', W + 'tbl') for child in node):
            raise ValueError(STRUCTURE_MESSAGE)
        if node.tag == W + 'tr':
            properties = node.find(W + 'trPr')
            if properties is not None and properties.find(W + 'del') is not None:
                revisions += 1
                return []
        if node.tag in COMMENT_TAGS:
            comments += 1
            return []
        if node.tag in HISTORY_TAGS or node.tag in DELETE_TAGS:
            revisions += 1
            return []
        unwrap = node.tag in ACCEPT_TAGS
        if unwrap:
            revisions += 1
        children = list(node)
        result = []
        changed = False
        for child in children:
            replacements = visit(child, node.tag)
            result.extend(replacements)
            changed |= len(replacements) != 1 or replacements[0] is not child
        if changed:
            for child in children:
                node.remove(child)
            node.extend(result)
        return list(node) if unwrap else [node]

    # A root paragraph/table is an externally bound source position, so it
    # cannot be unwrapped or removed. Inline children remain freely normalizable.
    if root.tag in DELETE_TAGS | ACCEPT_TAGS | COMMENT_TAGS | HISTORY_TAGS or root.tag == W + 'tr':
        raise ValueError(STRUCTURE_MESSAGE)
    visit(root)
    return RevisionView(revisions, comments)
