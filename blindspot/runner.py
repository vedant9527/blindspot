"""Keyboard runner: press Tab like a keyboard user and record every step.

Built at the event. See docs/SPEC.md section 3. The runner only gathers facts
(focused element, screenshots, pixel and coverage measurements); judging them
is the job of blindspot/checks.py.

CLI:  python -m blindspot.runner --url URL [--headless] [--tabs 40]
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from playwright.sync_api import Page

from blindspot import config
from blindspot.browser import CSS_PATH_FN, TABBABLE_COUNT_JS, focus_info

ROOT = Path(__file__).resolve().parent.parent

# Extra facts about the focused element that the checks need, gathered in one call.
STEP_EXTRA_JS = """
() => {
  const el = document.activeElement;
  if (!el || el === document.body || el === document.documentElement) return null;
  const short = n => {
    if (!n || n.nodeType !== 1) return '';
    let s = n.tagName.toLowerCase();
    if (n.id) s += '#' + n.id;
    else if (typeof n.className === 'string' && n.className.trim()) s += '.' + n.className.trim().split(/\\s+/).slice(0, 2).join('.');
    return s;
  };

  // Visual rect: the element's own box, or the union of its children when the box is empty
  // (an inline <a> wrapping block content reports a zero-height box but is visible).
  const r = el.getBoundingClientRect();
  let rect = {x: r.x, y: r.y, width: r.width, height: r.height};
  if (r.width * r.height === 0) {
    let x1 = Infinity, y1 = Infinity, x2 = -Infinity, y2 = -Infinity;
    for (const c of el.querySelectorAll('*')) {
      const cr = c.getBoundingClientRect();
      if (cr.width * cr.height > 0) {
        x1 = Math.min(x1, cr.left); y1 = Math.min(y1, cr.top);
        x2 = Math.max(x2, cr.right); y2 = Math.max(y2, cr.bottom);
      }
    }
    if (x1 < Infinity) rect = {x: x1, y: y1, width: x2 - x1, height: y2 - y1};
  }
  const vw = window.innerWidth, vh = window.innerHeight;
  const area = rect.width * rect.height;
  const offscreen = area > 0 && (rect.x + rect.width <= 0 || rect.y + rect.height <= 0 || rect.x >= vw || rect.y >= vh);

  // Nearest landmark, so an upward jump into a new region is not called an order problem.
  const LM = 'header,nav,main,footer,aside,dialog,form,[role=banner],[role=navigation],[role=main],' +
             '[role=contentinfo],[role=complementary],[role=search],[role=dialog],[role=region]';
  const lm = el.closest(LM);
  const landmark = lm ? (lm.getAttribute('role') || lm.tagName.toLowerCase()) + ':' +
                        Array.from(document.querySelectorAll(LM)).indexOf(lm) : null;

  // Visible label text: text a sighted user sees. Skips aria-hidden subtrees (icon ligatures),
  // hidden elements and visually-hidden screen-reader text (1px boxes).
  const hidden = node => {
    for (let e = node; e && e !== el.parentElement; e = e.parentElement) {
      if (e.getAttribute && e.getAttribute('aria-hidden') === 'true') return true;
      const s = getComputedStyle(e);
      if (s.display === 'none' || s.visibility === 'hidden' || parseFloat(s.opacity) === 0) return true;
      if (e !== el) { const er = e.getBoundingClientRect(); if (er.width <= 1 || er.height <= 1) return true; }
    }
    return false;
  };
  let label = '';
  if (el.tagName === 'INPUT' && ['submit', 'button', 'reset'].includes(el.type)) {
    label = el.value || '';
  } else {
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const t = walker.currentNode;
      if (t.textContent.trim() && !hidden(t.parentElement)) label += ' ' + t.textContent;
    }
  }
  label = label.replace(/\\s+/g, ' ').trim().slice(0, 300);

  // Coverage: sample the center and four inset corners with elementFromPoint.
  const ins = Math.max(1, Math.min(4, rect.width / 4, rect.height / 4));
  const pts = [[rect.x + rect.width / 2, rect.y + rect.height / 2],
               [rect.x + ins, rect.y + ins], [rect.x + rect.width - ins, rect.y + ins],
               [rect.x + ins, rect.y + rect.height - ins], [rect.x + rect.width - ins, rect.y + rect.height - ins]];
  let sampled = 0, covered = 0, fixedCovers = 0;
  const covering = [];
  if (area > 0) for (const [x, y] of pts) {
    if (x < 0 || y < 0 || x >= vw || y >= vh) continue;
    sampled++;
    const hit = document.elementFromPoint(x, y);
    if (!hit || hit === el || el.contains(hit) || hit.contains(el)) continue;
    covered++;
    for (let e = hit; e && e !== document.documentElement; e = e.parentElement) {
      const p = getComputedStyle(e).position;
      if (p === 'fixed' || p === 'sticky') { fixedCovers++; break; }
    }
    const d = short(hit);
    if (!covering.includes(d)) covering.push(d);
  }
  return {rect, offscreen, landmark, label_text: label,
          obscured: {sampled, covered, fixed_covers: fixedCovers, covering}};
}
"""

# Page-level facts: elements with a positive tabindex (rendered ones only).
PAGE_FACTS_JS = """
() => {
""" + CSS_PATH_FN + """
  const pos = [];
  for (const e of document.querySelectorAll('[tabindex]')) {
    const v = parseInt(e.getAttribute('tabindex'), 10);
    if (v > 0 && e.getClientRects().length > 0) {
      pos.push({selector: cssPath(e), tabindex: v, text: (e.innerText || '').trim().slice(0, 80)});
    }
  }
  return {positive_tabindex: pos};
}
"""

# Put the sequential-focus starting point at the top of the document without clicking
# anything (a click at a fixed spot could follow a link).
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


def focus_document_start(page: Page) -> None:
    """Move keyboard focus to the start of the document."""
    page.evaluate(FOCUS_START_JS)


def _selector_now(page: Page) -> str | None:
    info = page.evaluate("() => { const e = document.activeElement; return (!e || e === document.body) ? null : true; }")
    if info is None:
        return None
    fi = focus_info(page)
    return fi["selector"] if fi else None


def escape_test(page: Page, trapped: set[str | None]) -> dict[str, Any]:
    """Try to leave a suspected trap: Shift+Tab three times, then Escape followed by Tab.

    Focus reaching any element outside the trapped set (or leaving the page) counts as escaping.
    """
    seen = []
    shift_escaped = False
    for _ in range(3):
        page.keyboard.press("Shift+Tab")
        page.wait_for_timeout(config.STEP_WAIT_MS)
        sel = _selector_now(page)
        seen.append(sel)
        if sel not in trapped:
            shift_escaped = True
            break
    escape_escaped = None
    if not shift_escaped:
        page.keyboard.press("Escape")
        page.wait_for_timeout(config.STEP_WAIT_MS)
        page.keyboard.press("Tab")
        page.wait_for_timeout(config.STEP_WAIT_MS)
        sel = _selector_now(page)
        seen.append(sel)
        escape_escaped = sel not in trapped
    return {
        "selectors": sorted(s for s in trapped if s),
        "shift_tab_escaped": shift_escaped,
        "escape_key_escaped": escape_escaped,
        "focus_after": seen,
    }


def capture_step(page: Page, index: int, out_dir: Path) -> dict[str, Any]:
    """Record one step: focused element facts, full screenshot, crops and pixel measurements."""
    from blindspot.checks import crop_box, crop_png, pixel_stats  # local import keeps runner light

    vw = page.viewport_size["width"] if page.viewport_size else 1280
    step: dict[str, Any] = {"index": index, "selector": None, "tag": None}
    info = focus_info(page)
    extra = page.evaluate(STEP_EXTRA_JS) if info else None
    if extra and extra["offscreen"]:
        page.wait_for_timeout(config.OFFSCREEN_RECHECK_MS)  # give slide-in elements time to arrive
        extra = page.evaluate(STEP_EXTRA_JS) or extra

    full = page.screenshot()
    full_path = out_dir / "steps" / f"{index:02d}.png"
    full_path.write_bytes(full)
    step["full_screenshot"] = str(full_path)
    if not info:
        step["body"] = True  # focus is on the page body or has left the page
        return step

    step.update(info)
    step["element_rect"] = info["rect"]
    step.update({k: extra[k] for k in ("rect", "offscreen", "landmark", "label_text", "obscured")})

    rect = step["rect"]
    if not step["offscreen"] and rect["width"] * rect["height"] > 0:
        handle = page.evaluate_handle("document.activeElement")
        handle.evaluate("e => e.blur()")
        page.wait_for_timeout(config.STEP_WAIT_MS)  # let focus transitions finish
        blurred = page.screenshot()
        handle.evaluate("e => e.focus({preventScroll: true})")
        handle.dispose()
        step["pixels"] = pixel_stats(full, blurred, rect, vw)
        box = crop_box(rect, full, vw)
        if box:
            crop_dir = out_dir / "crops"
            focused_path = crop_dir / f"{index:02d}_focused.png"
            blurred_path = crop_dir / f"{index:02d}_unfocused.png"
            focused_path.write_bytes(crop_png(full, box))
            blurred_path.write_bytes(crop_png(blurred, box))
            step["focused_crop"] = str(focused_path)
            step["unfocused_crop"] = str(blurred_path)
    return step


def run_keyboard(page: Page, out_dir: Path | str, max_tabs: int = config.MAX_TABS,
                 timeout_s: float = config.RUN_TIMEOUT_S,
                 on_step: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
    """Tab through an already-loaded page and return every step plus page facts.

    Stops at max_tabs, after timeout_s, when focus cycles back to the first element,
    or when a keyboard trap is suspected (then runs the escape test).
    """
    out_dir = Path(out_dir)
    (out_dir / "steps").mkdir(parents=True, exist_ok=True)
    (out_dir / "crops").mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()

    page_facts = page.evaluate(PAGE_FACTS_JS)
    page_facts["tabbable"] = page.evaluate(TABBABLE_COUNT_JS)
    page_facts["url"] = page.url
    page_facts["viewport"] = page.viewport_size
    focus_document_start(page)

    steps: list[dict[str, Any]] = []
    stop_reason = "max_tabs"
    trap_test = None
    first_selector = None
    for i in range(1, max_tabs + 1):
        if time.perf_counter() - t0 > timeout_s:
            stop_reason = "timeout"
            break
        page.keyboard.press("Tab")
        page.wait_for_timeout(config.STEP_WAIT_MS)
        step = capture_step(page, i, out_dir)
        steps.append(step)
        if on_step:
            on_step(step)

        sel = step["selector"]
        seen = {s["selector"] for s in steps if s["selector"]}
        if first_selector is None and sel:
            first_selector = sel
        elif sel and sel == first_selector and len(seen) > config.TRAP_MAX_DISTINCT:
            stop_reason = "cycle"
            break

        recent = steps[-config.TRAP_WINDOW:]
        if (len(steps) >= config.TRAP_WINDOW and page_facts["tabbable"] >= config.TRAP_MIN_TABBABLE
                and not any(s["tag"] == "iframe" for s in recent)):  # focus inside an iframe looks stuck from outside
            selectors = [s["selector"] for s in recent]
            distinct = set(selectors)
            # Elements focused only once are the lead-in to the trap, not part of it.
            trapped = {s for s in distinct if selectors.count(s) >= 2}
            if len(distinct) <= config.TRAP_MAX_DISTINCT and trapped and trapped != {None}:
                trap_test = escape_test(page, trapped)
                stop_reason = "trap_suspected"
                break

    return {
        "page": page_facts,
        "steps": steps,
        "stop_reason": stop_reason,
        "trap_test": trap_test,
        "duration_s": round(time.perf_counter() - t0, 2),
        "out_dir": str(out_dir),
    }


def _print_step(step: dict[str, Any]) -> None:
    if step.get("body"):
        print(f"{step['index']:2d}. (focus on page body)")
        return
    r = step["rect"]
    px = step.get("pixels") or {}
    ob = step.get("obscured") or {}
    print(f"{step['index']:2d}. <{step['tag']}> role={step['role']!r} name={step['accessible_name'][:40]!r} "
          f"label={step['label_text'][:30]!r} at ({r['x']:.0f},{r['y']:.0f}) "
          f"changed_px={px.get('changed_px', '-')} covered={ob.get('covered', 0)}/{ob.get('sampled', 0)}"
          f"{' OFFSCREEN' if step.get('offscreen') else ''}")


def main() -> None:
    """Preflight, keyboard run and code checks on one URL; saves to runs/<run_id>/."""
    from playwright.sync_api import sync_playwright

    from blindspot.browser import launch_browser
    from blindspot.checks import run_checks
    from blindspot.preflight import run_preflight

    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--tabs", type=int, default=config.MAX_TABS)
    ap.add_argument("--headless", action="store_true")
    args = ap.parse_args()

    host = urlparse(args.url).netloc.replace("www.", "") or "local"
    run_id = f"{datetime.now():%Y%m%d-%H%M%S}-{host}"
    out_dir = ROOT / "runs" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = launch_browser(p, headless=args.headless)
        context = browser.new_context(viewport={"width": 1280, "height": 800},
                                      record_video_dir=str(out_dir / "video"))
        page = context.new_page()
        pre = run_preflight(page, args.url)
        print(f"Preflight: {pre.status} {pre.reason} (focusable: {pre.tabbable}, banner: {pre.banner_action})")
        if pre.status != "ok":
            context.close()
            browser.close()
            return
        run = run_keyboard(page, out_dir, max_tabs=args.tabs, on_step=_print_step)
        run["preflight"] = pre.__dict__
        context.close()
        browser.close()

    results = run_checks(run)
    (out_dir / "steps.json").write_text(json.dumps(run, indent=2), encoding="utf-8")
    (out_dir / "checks.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nStopped: {run['stop_reason']} after {len(run['steps'])} steps in {run['duration_s']}s")
    for r in results:
        tag = "PROVEN " if r["proven"] else "suspect"
        print(f"  {tag} {r['check']:<18} WCAG {r['wcag']:<7} step {r['evidence'].get('step', '-')}: {r['detail']}")
    if not results:
        print("  No code findings.")
    print(f"Saved to runs/{run_id}/")


if __name__ == "__main__":
    main()
