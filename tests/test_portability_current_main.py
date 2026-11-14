"""Keep the established OCR dispatch shape when adapters are not selected."""
from app import ocr


def test_default_ocr_dispatch_keeps_existing_callback_signatures(monkeypatch):
    seen = []
    monkeypatch.setattr(ocr, 'extract_text_from_pdf', lambda payload: seen.append(('pdf', payload)) or 'pdf text')
    monkeypatch.setattr(ocr, 'extract_text_from_image', lambda payload, suffix: seen.append((suffix, payload)) or 'image text')
    assert ocr.extract_text(b'pdf', 'example.pdf') == 'pdf text'
    assert ocr.extract_text(b'picture', 'example.png') == 'image text'
    assert seen == [('pdf', b'pdf'), ('.png', b'picture')]


def test_explicit_pdf_and_image_adapters_are_forwarded(monkeypatch):
    observed = []
    provider, reader, env = object(), object(), {'EPC_AI_PROVIDER': 'custom'}
    def pdf(payload, **kwargs):
        observed.append((payload, kwargs))
        return 'custom pdf'
    def image(payload, suffix, **kwargs):
        observed.append((payload, suffix, kwargs))
        return 'custom image'
    monkeypatch.setattr(ocr, 'extract_text_from_pdf', pdf)
    monkeypatch.setattr(ocr, 'extract_text_from_image', image)
    assert ocr.extract_text(b'pdf', 'example.pdf', provider=provider, reader=reader, env=env) == 'custom pdf'
    assert ocr.extract_text(b'image', 'example.png', provider=provider, env=env) == 'custom image'
    assert observed == [(b'pdf', {'provider': provider, 'reader': reader, 'env': env}),
                        (b'image', '.png', {'provider': provider, 'env': env})]
