"""Seeded accessibility bug injector (SPEC section 7).

Built at the event. Injects one of five WCAG failures into a loaded page using a
seeded RNG so results are reproducible and verifiable via a manifest + SHA-256.
"""

from __future__ import annotations

import hashlib
import json
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from playwright.sync_api import Page

from blindspot.browser import CSS_PATH_FN

BUG_TYPES: tuple[str, ...] = (
    "hide_focus",
    "keyboard_trap",
    "covering_banner",
    "positive_tabindex",
    "label_mismatch",
)

BUG_TO_CHECK: dict[str, str] = {
    "hide_focus": "focus_not_visible",
    "keyboard_trap": "keyboard_trap",
    "covering_banner": "focus_obscured",
    "positive_tabindex": "focus_order",
    "label_mismatch": "label_in_name",
}

CANDIDATES_JS = """
() => {
""" + CSS_PATH_FN + """
  const sel = 'a[href], button, input:not([type=hidden]), select, textarea, [role=button], [role=link], summary';
  const vw = window.innerWidth, vh = window.innerHeight;
  const out = [];
  for (const el of document.querySelectorAll(sel)) {
    if (el.hasAttribute('disabled') || el.getAttribute('aria-disabled') === 'true') continue;
    const ti = el.getAttribute('tabindex');
    if (ti !== null && parseInt(ti, 10) < 0) continue;
    const s = getComputedStyle(el);
    if (s.display === 'none' || s.visibility === 'hidden' || parseFloat(s.opacity) === 0) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 12 || r.height < 12) continue;
    const inFirstOne = (r.top >= 0 && r.top < vh && r.left >= 0 && r.left < vw);
    const inFirstTwo = (r.top >= 0 && r.top < vh * 2 && r.left >= 0 && r.left < vw);
    const tag = el.tagName.toLowerCase();
    const role = (el.getAttribute('role') || '').toLowerCase();
    const text = (el.innerText || el.value || '').replace(/\\s+/g, ' ').trim();
    const selector = cssPath(el);
    if (!selector) continue;
    out.push({
      selector,
      tag,
      role,
      text: text.slice(0, 120),
      in_first_one: inFirstOne,
      in_first_two: inFirstTwo,
      doc_y: r.top + window.scrollY,
      has_alnum: /[a-z0-9]{2,}/i.test(text),
      is_label_el: tag === 'a' || tag === 'button' || role === 'button' || role === 'link',
    });
  }
  return out;
}
"""

APPLY_BUG_JS = """
({selector, bug_type}) => {
  const el = document.querySelector(selector);
  if (!el) return false;
  el.setAttribute('data-bs-target', bug_type);

  if (bug_type === 'hide_focus') {
    const lockNode = (node, idx) => {
      const s = getComputedStyle(node);
      const attr = 'bs-hf-' + idx;
      node.setAttribute('data-bs-hf', attr);
      return '[data-bs-hf="' + attr + '"], [data-bs-target]:focus [data-bs-hf="' + attr + '"], ' +
             '[data-bs-target]:focus-visible [data-bs-hf="' + attr + '"] {' +
             '  outline: none !important; box-shadow: none !important;' +
             '  border-top: ' + s.borderTopWidth + ' ' + s.borderTopStyle + ' ' + s.borderTopColor + ' !important;' +
             '  border-right: ' + s.borderRightWidth + ' ' + s.borderRightStyle + ' ' + s.borderRightColor + ' !important;' +
             '  border-bottom: ' + s.borderBottomWidth + ' ' + s.borderBottomStyle + ' ' + s.borderBottomColor + ' !important;' +
             '  border-left: ' + s.borderLeftWidth + ' ' + s.borderLeftStyle + ' ' + s.borderLeftColor + ' !important;' +
             '  background-color: ' + s.backgroundColor + ' !important;' +
             '  color: ' + s.color + ' !important;' +
             '  opacity: ' + s.opacity + ' !important;' +
             '  text-decoration: ' + s.textDecorationLine + ' !important;' +
             '}';
    };
    const cb = getComputedStyle(el, '::before');
    const ca = getComputedStyle(el, '::after');
    let css = lockNode(el, 0);
    let i = 1;
    for (const child of el.querySelectorAll('*')) {
      css += lockNode(child, i++);
    }
    css +=
      '[data-bs-target]:focus, [data-bs-target]:focus-visible {' +
      '  outline: none !important; box-shadow: none !important;' +
      '}' +
      '[data-bs-target]:focus::before, [data-bs-target]:focus-visible::before {' +
      '  outline: none !important; box-shadow: none !important;' +
      '  opacity: ' + cb.opacity + ' !important; border-color: ' + cb.borderTopColor + ' !important;' +
      '}' +
      '[data-bs-target]:focus::after, [data-bs-target]:focus-visible::after {' +
      '  outline: none !important; box-shadow: none !important;' +
      '  opacity: ' + ca.opacity + ' !important; border-color: ' + ca.borderTopColor + ' !important;' +
      '}';
    const style = document.createElement('style');
    style.id = 'bs-inject-style';
    style.textContent = css;
    document.head.appendChild(style);
    return true;
  }

  if (bug_type === 'keyboard_trap') {
    const trap = (e) => {
      if (e.key === 'Tab' || e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        el.focus({preventScroll: true});
      }
    };
    el.addEventListener('keydown', trap, true);
    return true;
  }

  if (bug_type === 'covering_banner') {
    let banner = null;
    const place = () => {
      const r = el.getBoundingClientRect();
      if (!banner) {
        banner = document.createElement('div');
        banner.id = 'bs-inject-banner';
        banner.textContent = 'Special offer';
        Object.assign(banner.style, {
          position: 'fixed',
          zIndex: '2147483647',
          background: '#1f2937',
          color: '#ffffff',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          font: '600 14px/1.2 system-ui, sans-serif',
          boxSizing: 'border-box',
          pointerEvents: 'auto',
        });
        document.body.appendChild(banner);
      }
      const pad = 4;
      banner.style.left = Math.max(0, r.left - pad) + 'px';
      banner.style.top = Math.max(0, r.top - pad) + 'px';
      banner.style.width = (r.width + pad * 2) + 'px';
      banner.style.height = (r.height + pad * 2) + 'px';
    };
    el.addEventListener('focus', () => {
      place();
      requestAnimationFrame(place);
    });
    window.addEventListener('scroll', () => {
      if (document.activeElement === el && banner) place();
    }, {passive: true});
    return true;
  }

  if (bug_type === 'positive_tabindex') {
    el.setAttribute('tabindex', '1');
    return true;
  }

  if (bug_type === 'label_mismatch') {
    el.removeAttribute('aria-labelledby');
    el.setAttribute('aria-label', 'Menu item');
    return true;
  }

  return false;
}
"""


def inject(page: Page, bug_type: str, seed: int | None = None) -> dict[str, Any]:
    """Inject one accessibility bug into `page` and return its seeded manifest.

    `bug_type` must be one of `BUG_TYPES` or `"random"`. Picks a visible tabbable
    target using `random.Random(seed)` and tags it with `data-bs-target`.
    """
    if seed is None:
        seed = random.randint(1, 999_999)
    rng = random.Random(seed)

    if bug_type == "random":
        resolved = rng.choice(BUG_TYPES)
    elif bug_type in BUG_TYPES:
        resolved = bug_type
    else:
        raise ValueError(f"Unknown bug_type {bug_type!r}; choose from {BUG_TYPES} or 'random'")

    all_cands: list[dict[str, Any]] = page.evaluate(CANDIDATES_JS)
    if not all_cands:
        raise RuntimeError(f"No visible tabbable elements found on {page.url} to inject {resolved}")

    if resolved == "positive_tabindex":
        # Pick a random element near the bottom of the page
        by_y = sorted(all_cands, key=lambda c: c["doc_y"])
        bottom_n = max(1, len(by_y) // 3)
        pool = by_y[-bottom_n:]
    else:
        # Visible in the first two viewports (preferring the first viewport & early DOM order
        # so the 40-Tab runner reaches the target with room left for trap detection).
        first_two = [c for c in all_cands if c["in_first_two"]] or all_cands
        first_one = [c for c in first_two if c.get("in_first_one")] or first_two
        if resolved == "label_mismatch":
            label_pool = [
                c for c in first_one[:15]
                if c["is_label_el"] and c["has_alnum"] and c["text"].lower() != "menu item"
            ] or [
                c for c in first_two[:20]
                if c["is_label_el"] and c["has_alnum"] and c["text"].lower() != "menu item"
            ]
            pool = label_pool or [c for c in all_cands if c["is_label_el"] and c["has_alnum"]] or first_one[:15]
        else:
            pool = first_one[:15] or first_two[:15]

    target = rng.choice(pool)
    ok = page.evaluate(APPLY_BUG_JS, {"selector": target["selector"], "bug_type": resolved})
    if not ok:
        raise RuntimeError(f"Could not apply {resolved} to selector {target['selector']!r}")

    return {
        "url": page.url,
        "bug_type": resolved,
        "expected_check": BUG_TO_CHECK[resolved],
        "seed": seed,
        "target_selector": target["selector"],
        "target_text": target["text"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def manifest_sha256(manifest_path: Path | str) -> str:
    """Return the hex SHA-256 digest of a saved manifest file (for the held-out protocol)."""
    return hashlib.sha256(Path(manifest_path).read_bytes()).hexdigest()


def write_manifest(manifest: dict[str, Any] | list[dict[str, Any]], path: Path | str) -> str:
    """Write a manifest JSON file canonically and return its SHA-256 hex digest."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest_sha256(p)
