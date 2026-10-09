"""Pagination for rebuilt current tables, not unchanged source-table geometry."""
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph


def keep_current_header_with_rows(table):
    """The caller has supplied one explicit header and at least one data row."""
    rows = table.findall(qn('w:tr'))
    if len(rows) < 2:
        return
    for index, row in enumerate(rows):
        properties = row.get_or_add_trPr()
        # A one-row source prototype may mark every cloned data row as a header.
        for old in list(properties.findall(qn('w:tblHeader'))):
            properties.remove(old)
        if index == 0:
            header = OxmlElement('w:tblHeader')
            properties.insert_element_before(header, 'w:tblCellSpacing', 'w:jc', 'w:hidden',
                                             'w:ins', 'w:del', 'w:trPrChange')
        # The first data row must move intact with the header. Otherwise Writer
        # can carry an empty split fragment and leave nearly a whole page unused.
        if index <= 1:
            split = properties.find(qn('w:cantSplit'))
            if split is None:
                split = OxmlElement('w:cantSplit')
                properties.insert_element_before(split, 'w:trHeight', 'w:tblHeader',
                    'w:tblCellSpacing', 'w:jc', 'w:hidden', 'w:ins', 'w:del', 'w:trPrChange')
            split.set(qn('w:val'), '1')
        for node in row.iter(qn('w:p')):
            paragraph = Paragraph(node, None)
            # Explicit false also overrides a heading style inherited by data.
            # Otherwise one source header can keep the entire new table together.
            paragraph.paragraph_format.keep_with_next = index == 0
            if index == 0:
                paragraph.paragraph_format.keep_together = True
