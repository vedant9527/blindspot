"""Self-contained headless replay script (SPEC section 10).

NO imports from the rest of the repo: runs standalone locally or inside a Gemini
Managed Agent sandbox with only Python 3.12 stdlib + `playwright`.

CLI:
  python replay.py --url URL --tabs N --check CHECK [--inject-manifest FILE] [--har FILE]
Outputs one JSON line: {"reproduced": bool, "detail": str, ...}
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, sync_playwright

ACTIVE_DEEP_JS = """
  function activeDeep() {
    let el = document.activeElement;
    while (el && el.shadowRoot && el.shadowRoot.activeElement) el = el.shadowRoot.activeElement;
    return el;
  }
  function cssPathOne(node, rootDoc) {
    const root = rootDoc || document;
    const uniqueId = n => n.id && root.querySelectorAll('#' + CSS.escape(n.id)).length === 1;
    if (uniqueId(node)) return '#' + CSS.escape(node.id);
    const parts = [];
    while (node && node.nodeType === 1 && node !== document.documentElement && node !== root) {
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
  function cssPath(node) {
    const chain = [];
    let cur = node;
    while (cur) {
      const rn = cur.getRootNode ? cur.getRootNode() : document;
      if (rn && rn.host) { chain.unshift(cssPathOne(cur, rn)); cur = rn.host; }
      else { chain.unshift(cssPathOne(cur, document)); break; }
    }
    return chain.join(' >>> ');
  }
"""

FOCUS_START_JS = """
() => {
  window.scrollTo(0, 0);
  const a = document.activeElement;
  if (a && a !== document.body && a.blur) a.blur();
  const b = document.body;
  if (!b) return;
  const had = b.hasAttribute('tabindex');
  if (!had) b.setAttribute('tabindex', '-1');
  b.focus({preventScroll: true});
  if (!had) b.removeAttribute('tabindex');
}
"""

REAPPLY_INJECT_JS = """
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
             '  background-color: ' + s.backgroundColor + ' !important; color: ' + s.color + ' !important;' +
             '  opacity: ' + s.opacity + ' !important; text-decoration: ' + s.textDecorationLine + ' !important; }';
    };
    let css = lockNode(el, 0);
    let i = 1;
    for (const c of el.querySelectorAll('*')) css += lockNode(c, i++);
    css += '[data-bs-target]:focus, [data-bs-target]:focus-visible { outline: none !important; box-shadow: none !important; }';
    const st = document.createElement('style');
    st.textContent = css;
    document.head.appendChild(st);
    return true;
  }
  if (bug_type === 'keyboard_trap') {
    el.addEventListener('keydown', e => {
      if (e.key === 'Tab' || e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); el.focus({preventScroll: true}); }
    }, true);
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
          position: 'fixed', zIndex: '2147483647', background: '#1f2937', color: '#fff',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        });
        document.body.appendChild(banner);
      }
      const pad = 4;
      banner.style.left = Math.max(0, r.left - pad) + 'px';
      banner.style.top = Math.max(0, r.top - pad) + 'px';
      banner.style.width = (r.width + pad * 2) + 'px';
      banner.style.height = (r.height + pad * 2) + 'px';
    };
    el.addEventListener('focus', () => { place(); requestAnimationFrame(place); });
    return true;
  }
  if (bug_type === 'positive_tabindex') { el.setAttribute('tabindex', '1'); return true; }
  if (bug_type === 'label_mismatch') { el.removeAttribute('aria-labelledby'); el.setAttribute('aria-label', 'Menu item'); return true; }
  return false;
}
"""

DIFF_PNG_IN_BROWSER_JS = """
async ({b64a, b64b, rect, vw}) => {
  const load = b64 => new Promise((res, rej) => {
    const img = new Image();
    img.onload = () => res(img);
    img.onerror = rej;
    img.src = 'data:image/png;base64,' + b64;
  });
  const [ia, ib] = await Promise.all([load(b64a), load(b64b)]);
  const w = ia.width, h = ia.height;
  const ca = document.createElement('canvas'); ca.width = w; ca.height = h;
  const cb = document.createElement('canvas'); cb.width = w; cb.height = h;
  const xa = ca.getContext('2d'); xa.drawImage(ia, 0, 0);
  const xb = cb.getContext('2d'); xb.drawImage(ib, 0, 0);
  const da = xa.getImageData(0, 0, w, h).data;
  const db = xb.getImageData(0, 0, w, h).data;
  const scale = w / Math.max(1, vw);
  const pad = 12;
  const x0 = Math.max(0, Math.floor((rect.x - pad) * scale));
  const y0 = Math.max(0, Math.floor((rect.y - pad) * scale));
  const x1 = Math.min(w, Math.ceil((rect.x + rect.width + pad) * scale));
  const y1 = Math.min(h, Math.ceil((rect.y + rect.height + pad) * scale));
  let inCrop = 0, elsewhere = 0;
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const idx = (y * w + x) * 4;
      const d = Math.max(Math.abs(da[idx] - db[idx]), Math.abs(da[idx+1] - db[idx+1]), Math.abs(da[idx+2] - db[idx+2]));
      if (d > 24) {
        if (x >= x0 && x < x1 && y >= y0 && y < y1) inCrop++;
        else elsewhere++;
      }
    }
  }
  const areaScale = scale * scale;
  return { changed_px: Math.round(inCrop / areaScale), changed_elsewhere: Math.round(elsewhere / areaScale) };
}
"""


def _dismiss_banner(page: Page) -> None:
    import re

    for pat, sels in (
        (re.compile(r"reject|decline|necessary only|only necessary|refuse", re.I), ["#onetrust-reject-all-handler"]),
        (re.compile(r"^(close|dismiss|no thanks|x)\b", re.I), []),
        (re.compile(r"accept|agree|allow|got it|^ok$", re.I), ["#onetrust-accept-btn-handler"]),
    ):
        for s in sels:
            try:
                loc = page.locator(s).first
                if loc.is_visible(timeout=300):
                    loc.click(timeout=1000)
                    return
            except Exception:
                pass
        try:
            loc = page.get_by_role("button", name=pat).first
            if loc.is_visible(timeout=300):
                loc.click(timeout=1000)
                return
        except Exception:
            pass


def _selector_now(page: Page) -> str | None:
    return page.evaluate(
        "() => {" + ACTIVE_DEEP_JS + " const el = activeDeep(); return (!el || el === document.body) ? null : cssPath(el); }"
    )


def _norm(text: str) -> str:
    return "".join(ch for ch in (text or "").lower() if ch.isalnum())


def _accessible_name(page: Page) -> str:
    try:
        cdp = page.context.new_cdp_session(page)
        cdp.send("Accessibility.enable")
        res = cdp.send(
            "Runtime.evaluate",
            {
                "expression": "(() => { let e = document.activeElement; while (e && e.shadowRoot && e.shadowRoot.activeElement) e = e.shadowRoot.activeElement; return e; })()",
                "objectGroup": "bs_replay",
            },
        )
        oid = res.get("result", {}).get("objectId")
        if not oid:
            cdp.detach()
            return ""
        ax = cdp.send("Accessibility.getPartialAXTree", {"objectId": oid, "fetchRelatives": False})
        node = (ax.get("nodes") or [{}])[0]
        cdp.detach()
        return (node.get("name") or {}).get("value", "") or ""
    except Exception:
        return ""


def replay(url: str, tabs: int, check: str, manifest_path: str | None = None, har_path: str | None = None) -> dict[str, Any]:
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception:
            browser = p.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        if har_path and Path(har_path).exists():
            context.route_from_har(har_path, update=False)
        page = context.new_page()
        page.goto(url, timeout=15_000, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=2000)
        except Exception:
            pass
        _dismiss_banner(page)

        if manifest_path:
            manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
            page.evaluate(
                REAPPLY_INJECT_JS,
                {"selector": manifest["target_selector"], "bug_type": manifest["bug_type"]},
            )

        if check == "focus_order":
            pos = page.evaluate(
                "() => Array.from(document.querySelectorAll('[tabindex]'))"
                ".filter(e => parseInt(e.getAttribute('tabindex'), 10) > 0 && e.getClientRects().length > 0).length"
            )
            context.close()
            browser.close()
            return {"reproduced": pos > 0, "detail": f"Found {pos} rendered element(s) with positive tabindex"}

        page.evaluate(FOCUS_START_JS)
        for _ in range(max(1, tabs)):
            page.keyboard.press("Tab")
            page.wait_for_timeout(150)

        if check == "keyboard_trap":
            start_sel = _selector_now(page)
            seen = [start_sel]
            for _ in range(9):
                page.keyboard.press("Tab")
                page.wait_for_timeout(150)
                seen.append(_selector_now(page))
            distinct = set(seen)
            trapped = {s for s in distinct if seen.count(s) >= 2 and s}
            escaped = False
            if len(distinct) <= 2 and trapped:
                for _ in range(3):
                    page.keyboard.press("Shift+Tab")
                    page.wait_for_timeout(150)
                    if _selector_now(page) not in trapped:
                        escaped = True
                        break
                if not escaped:
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(150)
                    page.keyboard.press("Tab")
                    page.wait_for_timeout(150)
                    if _selector_now(page) not in trapped:
                        escaped = True
            repro = bool(len(distinct) <= 2 and trapped and not escaped)
            context.close()
            browser.close()
            return {"reproduced": repro, "detail": f"distinct={sorted(s for s in distinct if s)} escaped={escaped}"}

        if check == "focus_obscured":
            ob = page.evaluate(
                "() => {" + ACTIVE_DEEP_JS + """
                  const el = activeDeep();
                  if (!el || el === document.body) return {sampled: 0, covered: 0, fixed: 0};
                  const r = el.getBoundingClientRect();
                  const vw = window.innerWidth, vh = window.innerHeight;
                  const ins = Math.max(1, Math.min(4, r.width / 4, r.height / 4));
                  const pts = [[r.x + r.width/2, r.y + r.height/2], [r.x + ins, r.y + ins],
                               [r.x + r.width - ins, r.y + ins], [r.x + ins, r.y + r.height - ins],
                               [r.x + r.width - ins, r.y + r.height - ins]];
                  let sampled = 0, covered = 0, fixed = 0;
                  for (const [x, y] of pts) {
                    if (x < 0 || y < 0 || x >= vw || y >= vh) continue;
                    sampled++;
                    let hit = document.elementFromPoint(x, y);
                    while (hit && hit.shadowRoot && hit.shadowRoot.elementFromPoint) {
                      const inner = hit.shadowRoot.elementFromPoint(x, y);
                      if (!inner || inner === hit) break;
                      hit = inner;
                    }
                    if (!hit || hit === el || el.contains(hit) || hit.contains(el)) continue;
                    covered++;
                    for (let e = hit; e && e !== document.documentElement; e = e.parentElement || (e.getRootNode && e.getRootNode().host)) {
                      if (!e || e.nodeType !== 1) break;
                      const pos = getComputedStyle(e).position;
                      if (pos === 'fixed' || pos === 'sticky') { fixed++; break; }
                    }
                  }
                  return {sampled, covered, fixed};
                }"""
            )
            repro = bool(ob["sampled"] > 0 and ob["covered"] == ob["sampled"] == ob["fixed"])
            context.close()
            browser.close()
            return {"reproduced": repro, "detail": f"covered={ob['covered']}/{ob['sampled']} fixed={ob['fixed']}"}

        if check == "label_in_name":
            vis = page.evaluate(
                "() => {" + ACTIVE_DEEP_JS + " const el = activeDeep(); return el ? (el.innerText || el.value || '').trim() : ''; }"
            )
            acc = _accessible_name(page)
            repro = bool(_norm(vis) and _norm(vis) not in _norm(acc))
            context.close()
            browser.close()
            return {"reproduced": repro, "detail": f"visible={vis!r} accessible_name={acc!r}"}

        if check == "focus_not_visible":
            rect = page.evaluate(
                "() => {" + ACTIVE_DEEP_JS + " const el = activeDeep(); if (!el) return null; const r = el.getBoundingClientRect(); return {x: r.x, y: r.y, width: r.width, height: r.height}; }"
            )
            if not rect or rect["width"] * rect["height"] == 0:
                context.close()
                browser.close()
                return {"reproduced": False, "detail": "No focused element rect"}
            offscreen = rect["x"] + rect["width"] <= 0 or rect["y"] + rect["height"] <= 0 or rect["x"] >= 1280 or rect["y"] >= 800
            if offscreen:
                context.close()
                browser.close()
                return {"reproduced": True, "detail": "Focused element is offscreen"}
            f_png = page.screenshot()
            handle = page.evaluate_handle(
                "() => { let e = document.activeElement; while (e && e.shadowRoot && e.shadowRoot.activeElement) e = e.shadowRoot.activeElement; return e; }"
            )
            handle.evaluate("e => e.blur()")
            page.wait_for_timeout(150)
            u_png = page.screenshot()
            handle.dispose()
            stats = page.evaluate(
                DIFF_PNG_IN_BROWSER_JS,
                {
                    "b64a": base64.b64encode(f_png).decode("ascii"),
                    "b64b": base64.b64encode(u_png).decode("ascii"),
                    "rect": rect,
                    "vw": 1280,
                },
            )
            repro = bool(stats["changed_px"] < 8 and stats["changed_elsewhere"] <= 200)
            context.close()
            browser.close()
            return {"reproduced": repro, "detail": f"changed_px={stats['changed_px']} changed_elsewhere={stats['changed_elsewhere']}"}

        context.close()
        browser.close()
        return {"reproduced": False, "detail": f"Unsupported check {check!r}"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--tabs", type=int, default=1)
    ap.add_argument("--check", required=True)
    ap.add_argument("--inject-manifest", default=None)
    ap.add_argument("--har", default=None)
    args = ap.parse_args()
    try:
        res = replay(args.url, args.tabs, args.check, manifest_path=args.inject_manifest, har_path=args.har)
    except Exception as exc:
        res = {"reproduced": False, "detail": f"replay error: {exc}"}
    print(json.dumps(res))


if __name__ == "__main__":
    main()
