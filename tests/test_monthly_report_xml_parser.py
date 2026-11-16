"""The shared package parser must never accept entity-bearing report XML."""
from io import BytesIO

import pytest
from lxml import etree

from app.monthly_report_xml_parser import parse_xml, parse_xml_stream


@pytest.mark.parametrize("payload", [
    b'<!DOCTYPE root [<!ENTITY item "expanded">]><root>&item;</root>',
    b'<!DOCTYPE root SYSTEM "file:///etc/passwd"><root/>',
])
def test_package_parser_refuses_doctypes_and_entities(payload):
    with pytest.raises(etree.XMLSyntaxError):
        parse_xml(payload)
    with pytest.raises(etree.XMLSyntaxError):
        parse_xml_stream(BytesIO(payload))


def test_package_parser_preserves_namespaces_without_entities():
    payload = b'<w:document xmlns:w="urn:example"><w:body/></w:document>'
    root = parse_xml(payload)
    assert root.tag == "{urn:example}document"
    assert root.find("{urn:example}body") is not None
