"""Shared browser helpers: launching Chrome, reading the focused element.

Built at the event. Used by the keyboard runner, preflight and the spike scripts.
"""

from __future__ import annotations

from typing import Any

from playwright.sync_api import Browser, Page, Playwright

# Visible, tabbable elements on the page (approximation of the tab sequence).
TABBABLE_COUNT_JS = """
() => {
  const sel = 'a[href], button, input:not([type=hidden]), select, textarea, [tabindex], [contenteditable="true"], summary, iframe';
  return Array.from(document.querySelectorAll(sel)).filter(el => {
    if (el.hasAttribute('disabled')) return false;
    const ti = el.getAttribute('tabindex');
    if (ti !== null && parseInt(ti, 10) < 0) return false;
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
  }).length;
}
"""

# A stable CSS path for an element: id if unique, else tag plus nth-of-type chain.
CSS_PATH_FN = """
  function cssPath(node) {
    const uniqueId = n => n.id && document.querySelectorAll('#' + CSS.escape(n.id)).length === 1;
    if (uniqueId(node)) return '#' + CSS.escape(node.id);
    const parts = [];
    while (node && node.nodeType === 1 && node !== document.documentElement) {
      let part = node.tagName.toLowerCase();
      const parent = node.parentElement;
      if (parent) {
        const same = Array.from(parent.children).filter(c => c.tagName === node.tagName);
        if (same.length > 1) part += ':nth-of-type(' + (same.indexOf(node) + 1) + ')';
      }
      parts.unshift(part);
      if (parent && uniqueId(parent)) { parts.unshift('#' + CSS.escape(parent.id)); break; }
      node = parent;
    }
    return parts.join(' > ');
  }
"""

# Facts about document.activeElement, or null when focus is on <body>.
FOCUS_INFO_JS = """
() => {
""" + CSS_PATH_FN + """
  const el = document.activeElement;
  if (!el || el === document.body || el === document.documentElement) return null;
  const r = el.getBoundingClientRect();
  return {
    selector: cssPath(el),
    tag: el.tagName.toLowerCase(),
    role_attr: el.getAttribute('role'),
    aria_label: el.getAttribute('aria-label'),
    visible_text: (el.innerText || el.value || '').trim().slice(0, 200),
    rect: { x: r.x, y: r.y, width: r.width, height: r.height },
    scroll_y: window.scrollY,
    tabindex: el.getAttribute('tabindex'),
  };
}
"""


def launch_browser(p: Playwright, headless: bool = False) -> Browser:
    """Launch real Chrome if installed, otherwise Playwright's Chromium.

    Headed (visible) by default: it is what judges see, and headless browsers
    are flagged by bot protection far more often. Never add stealth tricks.
    """
    try:
        return p.chromium.launch(channel="chrome", headless=headless)
    except Exception:
        return p.chromium.launch(headless=headless)


def accessible_name_and_role(page: Page) -> dict[str, Any]:
    """Return the browser's computed accessible name and role for the focused element.

    Uses the Chrome DevTools Protocol accessibility tree, which is what assistive
    technology sees. Returns empty strings if it cannot be read.
    """
    try:
        cdp = page.context.new_cdp_session(page)
        cdp.send("Accessibility.enable")
        res = cdp.send("Runtime.evaluate", {"expression": "document.activeElement", "objectGroup": "blindspot"})
        object_id = res.get("result", {}).get("objectId")
        if not object_id:
            return {"name": "", "role": "", "ok": False}
        ax = cdp.send("Accessibility.getPartialAXTree", {"objectId": object_id, "fetchRelatives": False})
        node = (ax.get("nodes") or [{}])[0]
        cdp.detach()
        return {
            "name": (node.get("name") or {}).get("value", "") or "",
            "role": (node.get("role") or {}).get("value", "") or "",
            "ok": True,
        }
    except Exception:
        return {"name": "", "role": "", "ok": False}


def focus_info(page: Page) -> dict[str, Any] | None:
    """Everything we record about the focused element at one step."""
    info = page.evaluate(FOCUS_INFO_JS)
    if info is None:
        return None
    ax = accessible_name_and_role(page)
    info["accessible_name"] = ax["name"]
    info["role"] = ax["role"] or info.get("role_attr") or ""
    info["ax_ok"] = ax["ok"]  # False means the name could not be read; never treat that as an empty name
    return info
