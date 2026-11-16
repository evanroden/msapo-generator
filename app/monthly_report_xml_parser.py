"""Consistent, non-networked XML parsing for report and DOCX package parts.

A parser is made per call so concurrent report jobs do not share mutable parser
state. OOXML package members never require DTDs or entity declarations.
"""
from lxml import etree


def _parser():
    return etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)


def _reject_doctype(document):
    if document.docinfo.doctype:
        raise etree.XMLSyntaxError("DTD and entity declarations are not allowed in report XML.", 0, 0, 0)


def parse_xml(raw):
    """Parse package bytes without external or internal entity expansion."""
    root = etree.fromstring(raw, parser=_parser())
    _reject_doctype(root.getroottree())
    return root


def parse_xml_stream(source):
    """Parse a bounded file-like XML stream using the same safety policy."""
    document = etree.parse(source, parser=_parser())
    _reject_doctype(document)
    return document
