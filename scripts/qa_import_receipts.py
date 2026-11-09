"""Atomic, read-only native fixture receipt sampling after Streamlit settles."""
READY_RECEIPT_JS = r"""({selector, attribute, expected}) => {
  const app = document.querySelector('[data-testid="stApp"]');
  if (app?.getAttribute('data-test-script-state') !== 'notRunning') return false;
  const nodes = document.querySelectorAll(selector);
  if (nodes.length !== 1) return false;
  let value;
  try { value = JSON.parse(nodes[0].getAttribute(attribute)); }
  catch (_) { return false; }
  if (!value || typeof value !== 'object') return false;
  for (const [path, wanted] of Object.entries(expected)) {
    const actual = path.split('.').reduce((part, key) => part?.[key], value);
    if (JSON.stringify(actual) !== JSON.stringify(wanted)) return false;
  }
  return value;
}"""


def wait_receipt(page, attribute, expected=None, *, timeout=30000):
    """Return the same unique, idle, expected snapshot that passed the gate."""
    handle = page.wait_for_function(
        READY_RECEIPT_JS,
        arg={"selector": "[" + attribute + "]", "attribute": attribute,
             "expected": expected or {}}, timeout=timeout)
    try:
        return handle.json_value()
    finally:
        handle.dispose()
