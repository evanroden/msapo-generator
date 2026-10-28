from io import BytesIO
from PIL import Image

def png(color="navy"):
    out = BytesIO()
    Image.new("RGB", (64, 48), color).save(out, "PNG")
    return out.getvalue()

# Integration tests exercise the real rasterizer with a synthetic PDF backend;
# they do not require a live LibreOffice process or genuine client documents.
def test_rasterizer_rebuilds_damaged_cache(monkeypatch, tmp_path):
    from app import monthly_report_metafiles as vectors
    from app import monthly_report_library as library
    from app import monthly_report_word_pages as pages
    import pymupdf as fitz

    monkeypatch.setattr(library, "_root", lambda: tmp_path)
    monkeypatch.setattr(vectors, "supported_metafile", lambda raw, ext: True)
    monkeypatch.setattr(vectors, "_renderer_fingerprint", lambda *args: b"synthetic-font-and-renderer")
    monkeypatch.setattr(vectors, "_image_package", lambda *args: (b"synthetic passive DOCX", (144, 144)))
    count = []

    def fake_render(path, directory):
        count.append(path.read_bytes())
        with fitz.open() as pdf:
            page = pdf.new_page(width=612, height=792)
            page.draw_rect(fitz.Rect(0, 0, 144, 144), color=(0, 0, 0), fill=(0, 0, 0))
            target = directory / "synthetic-render.pdf"
            pdf.save(target)
        return target

    monkeypatch.setattr(pages, "_render", fake_render)
    raw = b"synthetic approved EMF original"
    first = vectors.rasterize_metafile(raw, ".emf")
    assert first.startswith(b"\x89PNG") and count == [b"synthetic passive DOCX"]
    assert vectors.rasterize_metafile(raw, ".emf") == first
    assert len(count) == 1
    cached = next((tmp_path / "imports" / "metafile-review").glob("*.png"))
    cached.write_bytes(b"damaged derivative")
    assert vectors.rasterize_metafile(raw, ".emf") == first
    assert len(count) == 2
    assert cached.read_bytes() == first
    assert raw == b"synthetic approved EMF original"


def test_invalid_cached_symlink_is_replaced_without_touching_target(monkeypatch, tmp_path):
    from app import monthly_report_metafiles as vectors
    from app import monthly_report_library as library
    from app import monthly_report_word_pages as pages
    import pymupdf as fitz

    monkeypatch.setattr(library, "_root", lambda: tmp_path)
    monkeypatch.setattr(vectors, "supported_metafile", lambda raw, ext: True)
    monkeypatch.setattr(vectors, "_renderer_fingerprint", lambda *args: b"symlink-renderer")
    monkeypatch.setattr(vectors, "_image_package", lambda *args: (b"synthetic", (100, 120)))

    def fake_render(path, directory):
        with fitz.open() as pdf:
            pdf.new_page(width=612, height=792).draw_rect(
                fitz.Rect(0, 0, 100, 120), color=(0, 0, 0), fill=(0, 0, 0))
            target = directory / "render.pdf"
            pdf.save(target)
        return target

    monkeypatch.setattr(pages, "_render", fake_render)
    raw = b"other synthetic supported EMF"
    first = vectors.rasterize_metafile(raw, ".emf")
    cached = next((tmp_path / "imports" / "metafile-review").glob("*.png"))
    private = tmp_path / "other-target.png"
    private.write_bytes(png(color="yellow"))
    before = private.read_bytes()
    cached.unlink()
    cached.symlink_to(private)
    assert vectors.rasterize_metafile(raw, ".emf") == first
    assert private.read_bytes() == before
    assert not cached.is_symlink()
