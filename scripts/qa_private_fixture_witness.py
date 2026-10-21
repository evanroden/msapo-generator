"""Opt-in read-only fixture witness; publish only an encrypted metadata receipt.

No upload, Start, Reset, Save, rendering, screenshots, traces or original-byte
artifacts. An opaque UUID commitment selects ONE approved existing original.
The recipient private key is never present in the repository or CI runner.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

AAD = b"enfra-private-fixture-witness-v1"
DOMAIN = b"enfra-readonly-target-v1:"
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
NATIVE = re.compile(r"st-key-_shared_fixture_download_([0-9a-f]{32})_([0-9a-f]{16})\Z")


def commitment(identity: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{32}", identity):
        raise ValueError("Invalid opaque identity.")
    return hashlib.sha256(DOMAIN + identity.encode("ascii")).hexdigest()


def native_identity(classes: list[str], displayed_prefix: str) -> tuple[str, str]:
    found = {match.groups() for value in classes for name in value.split()
             if (match := NATIVE.fullmatch(name))}
    if len(found) != 1:
        raise ValueError("No unique native original action.")
    identity, digest_prefix = next(iter(found))
    if identity[:8] != displayed_prefix:
        raise ValueError("Native action does not match selection.")
    return identity, digest_prefix


def seal(report: dict, public_pem: str) -> bytes:
    public = serialization.load_pem_public_key(public_pem.encode("ascii"))
    if not isinstance(public, rsa.RSAPublicKey) or public.key_size < 3072:
        raise ValueError("A recipient RSA public key of at least 3072 bits is required.")
    key, nonce = AESGCM.generate_key(bit_length=256), os.urandom(12)
    clear = json.dumps(report, sort_keys=True).encode("utf-8")
    encrypted = AESGCM(key).encrypt(nonce, clear, AAD)
    wrapped = public.encrypt(key, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),
                                             algorithm=hashes.SHA256(), label=AAD))
    b64 = lambda value: base64.b64encode(value).decode("ascii")
    return (json.dumps({"schema": 1, "algorithm": "RSA-OAEP-SHA256+AES-256-GCM",
                        "aad": b64(AAD), "wrapped_key": b64(wrapped),
                        "nonce": b64(nonce), "ciphertext": b64(encrypted)},
                       sort_keys=True) + "\n").encode("ascii")


def resolve_target(config: dict, progress: dict) -> tuple[str, str]:
    """Read selector metadata; never fetch an unrelated original in the browser."""
    from playwright.sync_api import sync_playwright, expect
    from scripts import qa_shared_fixture_redeploy_readonly as existing
    blocked, errors = [], []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context(service_workers="block")
            context.route("**/*", lambda route: existing._browser_route(route, blocked))
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(type(error).__name__))
            page.set_default_timeout(25000)
            progress["stage"] = "verify-served-build-before-selection"
            existing._served_commit(page, config["expected_commit"])
            page.goto(existing.ORIGIN + existing.FIXTURE_ROUTE,
                      wait_until="domcontentloaded", timeout=65000)
            expect(page.get_by_role("heading", name="Shared report testing", exact=True)).to_be_visible(timeout=60000)
            selector = page.get_by_role("combobox", name="Shared fixture", exact=True)
            expect(selector).to_be_visible(timeout=45000)
            selector.click()
            expect(page.get_by_role("listbox")).to_be_visible()
            choices = page.get_by_role("option").all_text_contents()
            page.keyboard.press("Escape")
            if not 1 <= len(choices) <= 32:
                raise ValueError("Unexpected bounded selector size.")
            progress["stage"] = "resolve-full-opaque-target"
            for label in choices:
                suffix = re.search(r" · ([0-9a-f]{8})$", label)
                if not suffix:
                    raise ValueError("Unexpected selector identity format.")
                selector.click()
                page.get_by_role("option", name=label, exact=True).click()
                native = page.locator('[class*="st-key-_shared_fixture_download_' + suffix[1] + '"]')
                expect(native).to_have_count(1, timeout=45000)
                expect(native).to_be_visible(timeout=45000)
                page.wait_for_function("""() => document.querySelector('[data-testid="stApp"]')
                    ?.getAttribute('data-test-script-state') === 'notRunning'""", timeout=45000)
                identity, digest_prefix = native_identity(
                    native.evaluate_all("nodes => nodes.map(n => n.className)"), suffix[1])
                if commitment(identity) != config["target_commitment"]:
                    continue
                detail = page.get_by_text(re.compile(r"^Original SHA256: [0-9a-f]{64}$"))
                expect(detail).to_have_count(1)
                digest = (detail.text_content() or "").split(": ")[-1]
                if not HEX64.fullmatch(digest) or digest[:16] != digest_prefix:
                    raise ValueError("Original metadata and native action disagree.")
                if blocked or errors:
                    raise ValueError("External request or browser error.")
                return identity, digest
            raise ValueError("Approved opaque target was not found.")
        finally:
            browser.close()


def self_test() -> None:
    """Synthetic cryptographic and identity controls; no network or real data."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    pem = key.public_key().public_bytes(serialization.Encoding.PEM,
                                      serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    report = {"secret": "INVENTED-PRIVATE-CANARY", "fixture_id": "a" * 32}
    raw = seal(report, pem)
    assert b"INVENTED-PRIVATE-CANARY" not in raw and b"a" * 32 not in raw
    envelope = json.loads(raw)
    get = lambda name: base64.b64decode(envelope[name], validate=True)
    aes = key.decrypt(get("wrapped_key"), padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),
                                                     algorithm=hashes.SHA256(), label=AAD))
    assert json.loads(AESGCM(aes).decrypt(get("nonce"), get("ciphertext"), AAD)) == report
    from cryptography.exceptions import InvalidTag
    try:
        AESGCM(aes).decrypt(get("nonce"), get("ciphertext")[:-1] + bytes([get("ciphertext")[-1] ^ 1]), AAD)
    except InvalidTag:
        pass
    else:
        raise AssertionError("Tamper was accepted.")
    assert native_identity(["other st-key-_shared_fixture_download_" + "a" * 32 + "_" + "b" * 16], "a" * 8) == ("a" * 32, "b" * 16)
    for values, prefix in (([], "a" * 8), (["st-key-_shared_fixture_download_" + "a" * 32 + "_" + "b" * 16], "c" * 8)):
        try:
            native_identity(values, prefix)
        except ValueError:
            pass
        else:
            raise AssertionError("Invalid native identity was accepted.")
    assert commitment("a" * 32) != commitment("b" * 32)
    print("PASS synthetic sealing, tamper rejection and native-identity controls", flush=True)


def main(config_path: str) -> int:
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    if not HEX64.fullmatch(config["target_commitment"]) or not HEX40.fullmatch(config["expected_commit"]):
        raise ValueError("Invalid public verifier configuration.")
    # Validate encryption BEFORE accessing any source metadata.
    seal({"bootstrap": True}, config["public_key"])
    progress = {"stage": "bootstrap", "expected_commit": config["expected_commit"],
                "verifier_commit": os.environ.get("GITHUB_SHA", ""),
                "workflow_run": os.environ.get("GITHUB_RUN_ID", ""),
                "started_at_utc": datetime.now(timezone.utc).isoformat()}
    accepted = False
    try:
        identity, digest = resolve_target(config, progress)
        progress["stage"] = "existing-full-byte-native-verifier"
        from scripts.qa_shared_fixture_redeploy_readonly import verify_one, _validate_manifest
        witness = verify_one(identity, digest, config["expected_commit"], "after")
        _validate_manifest(witness, "after")
        progress.update(stage="completed", accepted=True, witness=witness)
        accepted = True
    except Exception as exc:
        # Playwright exceptions may contain private selector text: encrypt them.
        progress.update(accepted=False, error_type=type(exc).__name__, private_error=str(exc)[:10000])
    progress["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    destination = Path("test-artifacts/private-fixture-witness/receipt.encrypted.json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as output:
        output.write(seal(progress, config["public_key"]))
    print("PASS encrypted read-only witness" if accepted else "FAIL read-only witness; diagnostics encrypted", flush=True)
    return 0 if accepted else 1


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        self_test()
    elif len(sys.argv) == 2:
        raise SystemExit(main(sys.argv[1]))
    else:
        raise SystemExit("Pass one public configuration path or --self-test.")
