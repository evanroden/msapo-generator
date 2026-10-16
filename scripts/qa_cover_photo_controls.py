"""One report-only Cover task before the isolated history read-only baseline.

The caller owns the real cookie, marked server, normal fixture load, network
guard and diagnostics. This helper never creates storage, a browser or output.
"""
from hashlib import sha256
from io import BytesIO
from urllib.parse import urljoin, urlparse

from PIL import Image, ImageDraw


FIXTURE_ASSET_BOUND = 64 * 1024
PHOTO_SIZE = (420, 250)
PHOTO_COLOR = (202, 179, 235)


def photograph():
    image = Image.new("RGB", PHOTO_SIZE, PHOTO_COLOR)
    ImageDraw.Draw(image).text((25, 105), "SYNTHETIC COVER PHOTOGRAPH", fill="black")
    raw = BytesIO()
    image.save(raw, "PNG")
    return raw.getvalue()


def unchanged_shared(before, after):
    assert after["scope"] == before["scope"] and after["generation"] == before["generation"]
    assert after["saved_revision"] == before["saved_revision"] == 3
    assert after["versions"] == before["versions"]
    assert after["working"]["without_cover"] == before["working"]["without_cover"], "A photo action changed other report content."
    old_assets = {item[0]: item[1:] for item in before["memory_assets"]}
    new_assets = {item[0]: item[1:] for item in after["memory_assets"]}
    assert all(new_assets.get(reference) == value for reference, value in old_assets.items()), "A photo action changed or dropped an existing in-memory asset."
    cover_refs = {item["reference"] for item in after["working"]["cover"]["assets"]}
    assert set(new_assets) - set(old_assets) <= cover_refs, "A photo action added unrelated assets."
    for group in ("history", "standing", "assets"):
        assert after["storage"]["groups"][group] == before["storage"]["groups"][group], "A report photo action changed shared " + group


def selected_asset(state):
    cover = state["working"]["cover"]
    assert cover == state["durable"]["cover"], "The photograph was not durably acknowledged."
    assert len(cover["assets"]) == 1
    asset = cover["assets"][0]
    assert 0 < asset["bytes"] <= FIXTURE_ASSET_BOUND, "The small invented photo exceeded its fixture bound."
    assert asset["reference"] == asset["sha256"] + ".jpg"
    assert [asset["reference"], asset["bytes"], asset["sha256"]] in state["memory_assets"]
    return asset


def exercise_cover_photo(page, identity, base, token, evidence, *, receipt, await_state,
                         storage_state, url, port, author, activity, output):
    from playwright.sync_api import expect

    stages = []
    evidence["cover_photograph"] = {"stages": stages, "fixture_asset_byte_bound": FIXTURE_ASSET_BOUND,
        "application_image_limit_bytes": 30 * 1024 * 1024,
        "scope": "Report-only native upload/use/omission and reload. No export or native-master visual acceptance."}

    def capture(stage, *, after=0, same=None):
        evidence["phase"] = "cover-" + stage
        current = await_state(page, identity, revision=3, author=author, activity=activity, photos=2, after=after)
        state = {key: current[key] for key in ("scope", "generation", "saved_revision", "working", "durable", "versions", "memory_assets")}
        state["storage"] = storage_state(base, token)
        assert state["storage"]["live_library_absent"]
        assert state["storage"]["scope"] == identity and state["storage"]["generation"] == current["generation"]
        if same is not None:
            assert state == same, "A display, upload-only or reload action changed the acknowledged report/storage."
        stages.append({"stage": stage, **state})
        return state

    panel = page.locator(".st-key-epc_pair_monthly_cover").get_by_test_id("stExpander").filter(
        has=page.locator("summary").get_by_text("Change cover photograph", exact=True))
    baseline = capture("before")
    assert baseline["working"]["cover"] is None, "The ordinary fixture starts without an invented cover photo."
    panel.locator("summary").click()
    expect(panel.get_by_text("No cover photograph in this report (optional).", exact=True)).to_be_visible()
    capture("opened", same=baseline)
    raw = photograph()
    assert 0 < len(raw) <= FIXTURE_ASSET_BOUND
    (output / "synthetic-cover-upload.png").write_bytes(raw)
    evidence["cover_photograph"].update(original_sha256=sha256(raw).hexdigest(), original_bytes=len(raw))
    sequence = receipt(page)["sequence"]
    panel.get_by_test_id("stFileUploader").filter(
        has=page.get_by_text("New photograph for this report", exact=True)).locator('input[type="file"]').set_input_files(
            {"name": "synthetic-current-report-cover.png", "mimeType": "image/png", "buffer": raw})
    capture("uploaded-not-used", after=sequence, same=baseline)
    expect(panel.get_by_role("button", name="Use this photograph", exact=True)).to_be_visible()
    sequence = receipt(page)["sequence"]
    panel.get_by_role("button", name="Use this photograph", exact=True).click()
    included = capture("used", after=sequence)
    unchanged_shared(baseline, included)
    assert included["working"]["cover"]["source"] == "Replace once"
    assert included["working"]["cover"]["pending_review"] == [0], "A new photograph must not inherit review."
    asset = selected_asset(included)
    evidence["cover_photograph"]["normalized_asset"] = asset

    def visible_photo():
        image = panel.locator('[data-testid="stImage"] img')
        expect(image).to_have_count(1)
        image.scroll_into_view_if_needed()
        expect(image).to_be_visible()
        assert image.evaluate("""image => {
          const r=image.getBoundingClientRect();
          return Math.max(0,Math.min(r.right,innerWidth)-Math.max(r.left,0))*
            Math.max(0,Math.min(r.bottom,innerHeight)-Math.max(r.top,0)) >= r.width*r.height*.5;
        }"""), "The actual photograph must intersect the viewport after normal scrolling."
        assert image.evaluate("async image => {await image.decode();return image.naturalWidth>0;}")
        address = urljoin(url, image.get_attribute("src"))
        parsed = urlparse(address)
        assert parsed.hostname == "127.0.0.1" and parsed.port == port
        response = page.request.get(address, max_redirects=0)
        assert response.ok
        rendered = response.body()
        assert len(rendered) == asset["bytes"] and sha256(rendered).hexdigest() == asset["sha256"]
        with Image.open(BytesIO(rendered)) as decoded:
            assert decoded.format == "JPEG" and decoded.size == PHOTO_SIZE
            assert all(abs(actual - expected) <= 4 for actual, expected in zip(decoded.convert("RGB").getpixel((2, 2)), PHOTO_COLOR))
        (output / "normalized-cover-photograph.jpg").write_bytes(rendered)

    visible_photo()
    page.set_viewport_size({"width": 390, "height": 844})
    page.wait_for_function("() => document.querySelector('.epc-workspace')?.dataset.epcMode==='compact'")
    visible_photo()
    capture("narrow-current-photograph", same=included)
    page.screenshot(path=str(output / "narrow-cover-photograph.png"), full_page=False)
    sequence = receipt(page)["sequence"]
    panel.get_by_role("button", name="No cover photograph", exact=True).click()
    omitted = capture("left-out", after=sequence)
    unchanged_shared(baseline, omitted)
    assert omitted["working"]["cover"]["source"] == "Omit"
    assert selected_asset(omitted) == asset, "Omission must retain the exact photograph bytes."
    expect(panel.locator('[data-testid="stImage"] img')).to_have_count(0)
    page.reload(wait_until="domcontentloaded")
    capture("reloaded-omission", same=omitted)
    panel.locator("summary").click()
    expect(panel.get_by_text("No cover photograph in this report (optional).", exact=True)).to_be_visible()
    expect(panel.locator('[data-testid="stImage"] img')).to_have_count(0)
    capture("reopened-omitted-photograph", same=omitted)
    page.set_viewport_size({"width": 1365, "height": 900})
    page.wait_for_function("() => document.querySelector('.epc-workspace')?.dataset.epcMode==='wide'")
    capture("wide-return", same=omitted)
