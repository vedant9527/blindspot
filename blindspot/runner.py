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
from blindspot.browser import ACTIVE_DEEP_FN, CSS_PATH_FN, TABBABLE_COUNT_JS, focus_info

ROOT = Path(__file__).resolve().parent.parent

# Extra facts about the focused element that the checks need, gathered in one call.
STEP_EXTRA_JS = """
() => {
""" + ACTIVE_DEEP_FN + """
  const { el } = activeDeep();
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
      const p = getComputedStyle(e).position;
      if (p === 'fixed' || p === 'sticky') { fixedCovers++; break; }
    }
    const d = short(hit);
    if (!covering.includes(d)) covering.push(d);
  }
  // Is focus inside a popup? A dialog, or a fixed layer covering a quarter of the screen or more.
  let in_overlay = false;
  for (let e = el; e && e !== document.body; e = e.parentElement || (e.getRootNode && e.getRootNode().host)) {
    if (!e || e.nodeType !== 1) break;
    if (e.matches('[role=dialog],[role=alertdialog],[aria-modal=true],dialog[open]')) { in_overlay = true; break; }
    if (getComputedStyle(e).position === 'fixed') {
      const fr = e.getBoundingClientRect();
      if (fr.width * fr.height >= 0.25 * vw * vh) { in_overlay = true; break; }
    }
  }
  return {rect, offscreen, landmark, label_text: label, in_overlay,
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
    step.update({k: extra[k] for k in ("rect", "offscreen", "landmark", "label_text", "obscured", "in_overlay")})

    rect = step["rect"]
    if not step["offscreen"] and rect["width"] * rect["height"] > 0:
        handle = page.evaluate_handle(
            "() => { let e = document.activeElement; while (e && e.shadowRoot && e.shadowRoot.activeElement) e = e.shadowRoot.activeElement; return e; }"
        )
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
                 on_step: Callable[[dict[str, Any]], None] | None = None,
                 dismiss_popup: Callable[[Page], str] | None = None) -> dict[str, Any]:
    """Tab through an already-loaded page and return every step plus page facts.

    Stops at max_tabs, after timeout_s, when focus goes round the page and repeats,
    or when a keyboard trap is suspected (then runs the escape test). If focus lands
    in a popup and dismiss_popup is given, it is called (and logged) and the run restarts.
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
    popups: list[dict[str, Any]] = []
    cycle_start = 0  # steps before this index belong to an earlier pass (before a popup was closed)
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

        # A popup that appeared after load (e-mail sign-up, survey): close it the way a user would
        # (reject, then close, then accept), log it, and start again from the top of the page.
        if step.get("in_overlay") and dismiss_popup and len(popups) < config.MAX_POPUP_CLOSES:
            action = dismiss_popup(page)
            popups.append({"step": i, "action": action, "selector": step["selector"]})
            if action != "none":
                step["popup_closed"] = action
                page.wait_for_timeout(500)
                focus_document_start(page)
                cycle_start = len(steps)
                continue

        sel = step["selector"]
        current = steps[cycle_start:]
        earlier = [s["selector"] for s in current[:-1]]
        if sel and sel in earlier:
            loop_steps = current[earlier.index(sel):-1]
            if len({s["selector"] for s in loop_steps}) > config.TRAP_MAX_DISTINCT:
                stop_reason = "cycle"  # focus went all the way round and came back
                break

        recent = current[-config.TRAP_WINDOW:]
        if (len(recent) >= config.TRAP_WINDOW and page_facts["tabbable"] >= config.TRAP_MIN_TABBABLE
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
        "popups": popups,
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
          f"{' OFFSCREEN' if step.get('offscreen') else ''}"
          f"{' -> closed popup (' + step['popup_closed'] + ')' if step.get('popup_closed') else ''}")


def _step_has_order_jump(step: dict[str, Any], prev: dict[str, Any] | None) -> bool:
    """True when focus jumped more than ORDER_JUMP_PX upward within the same landmark."""
    if not prev or step.get("body") or prev.get("body") or not step.get("rect") or not prev.get("rect"):
        return False
    prev_top = prev["rect"]["y"] + prev.get("scroll_y", 0)
    top = step["rect"]["y"] + step.get("scroll_y", 0)
    return (prev_top - top > config.ORDER_JUMP_PX) and (step.get("landmark") == prev.get("landmark"))


def _score_step_worker(
    step: dict[str, Any],
    prev_rect: dict[str, float] | None,
    include_order: bool,
    under_overlay: bool,
    out_dir: Path,
    viewport_width: int,
    call_log: list[dict[str, Any]],
) -> dict[str, Any]:
    """Run Hydrogen `read_step` and Decisions `score_step` concurrently for one step."""
    from concurrent.futures import ThreadPoolExecutor

    from blindspot.checks import LABEL_ROLES, LABEL_TAGS, NO_LABEL_TAGS
    from blindspot.gemini import make_boxed_crop, read_step, score_step

    full_bytes = Path(step["full_screenshot"]).read_bytes()
    raw_crop = Path(step["focused_crop"]).read_bytes() if step.get("focused_crop") else None

    boxed_crop_bytes: bytes | None = None
    boxed_full_bytes = full_bytes
    boxed_path_str: str | None = None
    if not step.get("offscreen") and step.get("rect"):
        boxed_crop_bytes, boxed_full_bytes = make_boxed_crop(full_bytes, step["rect"], viewport_width=viewport_width)
        if boxed_crop_bytes:
            boxed_path = out_dir / "crops" / f"{step['index']:02d}_boxed.png"
            boxed_path.write_bytes(boxed_crop_bytes)
            boxed_path_str = str(boxed_path)

    tag, role = step.get("tag"), step.get("role")
    include_label = bool(
        step.get("ax_ok")
        and tag not in NO_LABEL_TAGS
        and (tag in LABEL_TAGS or role in LABEL_ROLES)
        and (step.get("label_text") or step.get("accessible_name"))
    )
    # Per HANDOFF.md / Phase 3 spec: never send indicator_contrast to the scorer when under an overlay.
    include_contrast = (not under_overlay) and (not step.get("offscreen")) and (tag != "iframe")

    r = step.get("rect") or {"x": 0, "y": 0, "width": 0, "height": 0}
    px = step.get("pixels") or {}
    ob = step.get("obscured") or {}
    ctx_lines = [
        "Accessibility check of one keyboard Tab step.",
        "NOTE: The bright red outer rectangle was drawn by our harness to show which element has keyboard focus — "
        "it is NOT part of the web page and NOT a focus indicator.",
        f"Step {step['index']}: <{tag}> role={role!r} selector={step.get('selector')!r}",
        f"Announced accessible name: {step.get('accessible_name', '')!r}",
        f"DOM visible label text: {step.get('label_text', '')!r}",
        f"Bounding rect: ({r['x']:.0f}, {r['y']:.0f}, {r['width']:.0f}x{r['height']:.0f})"
        + (" [OFFSCREEN]" if step.get("offscreen") else ""),
        f"Pixels changed on focus inside crop: {px.get('changed_px', 'n/a')}, contrast: {px.get('contrast', 'n/a')}",
        f"Hit-test coverage: {ob.get('covered', 0)}/{ob.get('sampled', 0)} sample points covered"
        + (f" by {', '.join(ob.get('covering', []))}" if ob.get("covering") else ""),
    ]
    if include_order and prev_rect:
        ctx_lines.append(
            f"Previous focused element rect was at ({prev_rect['x']:.0f}, {prev_rect['y']:.0f}); "
            f"current element is at ({r['x']:.0f}, {r['y']:.0f})."
        )
    context_text = "\n".join(ctx_lines)

    out: dict[str, Any] = {"boxed_crop": boxed_path_str, "reader": None, "scores": None, "errors": []}
    with ThreadPoolExecutor(max_workers=2) as sub:
        fut_read = sub.submit(read_step, raw_crop, full_bytes, call_log=call_log)
        fut_score = sub.submit(
            score_step,
            boxed_crop_bytes,
            boxed_full_bytes,
            context_text,
            accessible_name=step.get("accessible_name", ""),
            include_label=include_label,
            include_contrast=include_contrast,
            include_order=include_order,
            call_log=call_log,
        )
        try:
            out["reader"] = fut_read.result()
        except Exception as exc:
            out["errors"].append(f"read_step: {exc}")
        try:
            out["scores"] = fut_score.result()
        except Exception as exc:
            out["errors"].append(f"score_step: {exc}")
    return out


def _rel_path(p: str | None) -> str | None:
    if not p:
        return None
    try:
        return "/" + str(Path(p).resolve().relative_to(ROOT.resolve())).replace("\\", "/")
    except Exception:
        return p


def run_audit(
    url: str,
    *,
    run_id: str | None = None,
    out_dir: Path | None = None,
    headless: bool = False,
    max_tabs: int = config.MAX_TABS,
    inject: str | None = None,
    seed: int | None = None,
    use_gemini: bool = True,
    record_video: bool = True,
    write_tickets: bool = True,
    emit: Callable[[str, dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Full Phase 3 run: preflight (+ warm-up), keyboard loop + parallel Gemini scoring, decision rule.

    Streams SSE-ready events via `emit(event_type, payload)` and saves artifacts to `runs/<run_id>/`.
    """
    from concurrent.futures import Future, ThreadPoolExecutor
    from playwright.sync_api import sync_playwright

    from blindspot.axe_runner import run_axe
    from blindspot.browser import launch_browser
    from blindspot.checks import run_checks
    from blindspot.decide import decide_findings, filter_checks_for_scoring, is_under_overlay
    from blindspot.gemini import score_page_state, summarize_calls
    from blindspot.injector import inject as inject_bug, write_manifest
    from blindspot.preflight import dismiss_banner, run_preflight
    from blindspot.tickets import generate_tickets

    host = urlparse(url).netloc.replace("www.", "") or Path(urlparse(url).path).stem or "local"
    run_id = run_id or f"{datetime.now():%Y%m%d-%H%M%S}-{host}"
    out_dir = Path(out_dir) if out_dir else (ROOT / "runs" / run_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    log_lines: list[str] = []
    call_log: list[dict[str, Any]] = []

    def _log(msg: str) -> None:
        line = f"[{datetime.now():%H:%M:%S}] {msg}"
        log_lines.append(line)

    def _emit(event: str, data: dict[str, Any]) -> None:
        if emit:
            emit(event, data)

    _log(f"Starting run {run_id} url={url} headless={headless} use_gemini={use_gemini} inject={inject} seed={seed}")
    t_run0 = time.perf_counter()

    with sync_playwright() as p:
        browser = launch_browser(p, headless=headless)
        if record_video:
            try:
                context = browser.new_context(
                    viewport={"width": 1280, "height": 800},
                    record_video_dir=str(out_dir / "video"),
                )
                page = context.new_page()
            except Exception as exc:
                _log(f"Video recording off: {str(exc).splitlines()[0][:80]}")
                context = browser.new_context(viewport={"width": 1280, "height": 800})
                page = context.new_page()
        else:
            context = browser.new_context(viewport={"width": 1280, "height": 800})
            page = context.new_page()

        pre = run_preflight(page, url)
        page_state_info: dict[str, Any] | None = None
        if use_gemini and pre.status == "ok":
            try:
                pre_png = page.screenshot()
                page_state_info = score_page_state(pre_png, call_log=call_log)
                _log(
                    f"Preflight warm-up Decisions: page_state={page_state_info['choice']} "
                    f"({page_state_info['confidence']}) in {page_state_info['latency_s']}s"
                )
            except Exception as exc:
                _log(f"Preflight warm-up failed: {exc}")

        pre_payload = {
            "run_id": run_id,
            "status": pre.status,
            "reason": pre.reason,
            "http_status": pre.http_status,
            "tabbable": pre.tabbable,
            "banner_action": pre.banner_action,
            "final_url": pre.final_url,
            "page_state": page_state_info,
        }
        _emit("preflight", pre_payload)
        _log(f"Preflight: {pre.status} {pre.reason} (tabbable={pre.tabbable}, banner={pre.banner_action})")

        if pre.status != "ok":
            context.close()
            browser.close()
            summary = {
                "run_id": run_id,
                "status": "blocked",
                "reason": pre.reason,
                "preflight": pre_payload,
                "vetted_hint": "Pick a vetted public healthcare page from eval/pages_ok.txt (/api/vetted).",
                "duration_s": round(time.perf_counter() - t_run0, 2),
            }
            (out_dir / "steps.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
            (out_dir / "findings.json").write_text(
                json.dumps({"confirmed": [], "needs_human": [], "dropped": [], "findings": []}, indent=2),
                encoding="utf-8",
            )
            (out_dir / "run.log").write_text("\n".join(log_lines) + "\n", encoding="utf-8")
            _emit("done", summary)
            return summary

        late = dismiss_banner(page)
        if late != "none":
            _log(f"Late popup dismissed before run: {late}")
            page.wait_for_timeout(500)

        manifest: dict[str, Any] | None = None
        if inject:
            manifest = inject_bug(page, inject, seed=seed)
            manifest_hash = write_manifest(manifest, out_dir / "manifest.json")
            manifest["sha256"] = manifest_hash
            _log(
                f"Injected bug={manifest['bug_type']} seed={manifest['seed']} "
                f"target={manifest['target_selector']} sha256={manifest_hash[:12]}"
            )

        vw = page.viewport_size["width"] if page.viewport_size else 1280
        step_futures: dict[int, Future[dict[str, Any]]] = {}
        prev_step_holder: list[dict[str, Any] | None] = [None]
        pool = ThreadPoolExecutor(max_workers=config.SCORER_WORKERS) if use_gemini else None

        def _on_step(step: dict[str, Any]) -> None:
            _emit(
                "step",
                {
                    "run_id": run_id,
                    "index": step["index"],
                    "body": bool(step.get("body")),
                    "selector": step.get("selector"),
                    "tag": step.get("tag"),
                    "role": step.get("role"),
                    "accessible_name": step.get("accessible_name", ""),
                    "label_text": step.get("label_text", ""),
                    "rect": step.get("rect"),
                    "offscreen": bool(step.get("offscreen")),
                    "popup_closed": step.get("popup_closed"),
                    "full_screenshot": _rel_path(step.get("full_screenshot")),
                    "focused_crop": _rel_path(step.get("focused_crop")),
                },
            )
            if step.get("body"):
                return
            prev_s = prev_step_holder[0]
            include_order = _step_has_order_jump(step, prev_s)
            under_ov = is_under_overlay(step)
            prev_rect = dict(prev_s["rect"]) if (prev_s and prev_s.get("rect")) else None
            prev_step_holder[0] = step
            if pool is not None:
                step_futures[step["index"]] = pool.submit(
                    _score_step_worker,
                    step,
                    prev_rect,
                    include_order,
                    under_ov,
                    out_dir,
                    vw,
                    call_log,
                )

        axe_res: dict[str, Any] = {"violations": [], "violation_count": 0, "mapped_bugs": [], "mapped_checks": []}
        try:
            run = run_keyboard(
                page,
                out_dir,
                max_tabs=max_tabs,
                on_step=_on_step,
                dismiss_popup=dismiss_banner,
            )
            axe_res = run_axe(page)
            _log(
                f"axe-core: {axe_res['violation_count']} violations "
                f"(mapped_bugs={axe_res['mapped_bugs']}) in {axe_res.get('duration_s', 0)}s"
            )
        finally:
            context.close()
            browser.close()

        # Wait for in-flight parallel Gemini step tasks to finish
        if pool is not None:
            steps_by_idx = {s["index"]: s for s in run["steps"]}
            for idx, fut in step_futures.items():
                try:
                    res = fut.result(timeout=config.GEMINI_TIMEOUT_S * 3)
                    st = steps_by_idx[idx]
                    if res.get("boxed_crop"):
                        st["boxed_crop"] = res["boxed_crop"]
                    if res.get("reader") is not None:
                        st["reader"] = res["reader"]
                    if res.get("scores") is not None:
                        st["scores"] = res["scores"]
                    if res.get("errors"):
                        st["gemini_errors"] = res["errors"]
                        for err in res["errors"]:
                            _log(f"Step {idx} {err}")
                except Exception as exc:
                    _log(f"Step {idx} worker failed: {exc}")
            pool.shutdown(wait=False)

    run["run_id"] = run_id
    run["late_banner_action"] = late
    run["preflight"] = pre_payload
    if manifest is not None:
        run["manifest"] = manifest
    run["axe"] = axe_res
    raw_checks = run_checks(run)
    steps_map = {s["index"]: s for s in run["steps"]}
    filtered_checks = filter_checks_for_scoring(raw_checks, steps_map)
    decisions = decide_findings(run, filtered_checks)
    gemini_summary = summarize_calls(call_log)
    total_duration = round(time.perf_counter() - t_run0, 2)

    run["gemini_usage"] = gemini_summary
    run["total_duration_s"] = total_duration

    # Stream findings over SSE (with web-accessible crop paths attached)
    for finding in decisions["findings"]:
        ev = finding.get("evidence") or {}
        sse_finding = {
            **finding,
            "run_id": run_id,
            "crop_url": _rel_path(ev.get("boxed_crop") or ev.get("focused_crop")),
            "screenshot_url": _rel_path(ev.get("full_screenshot")),
        }
        _emit("finding", sse_finding)

    _emit("axe", {"run_id": run_id, **axe_res})

    tickets: list[dict[str, Any]] = []
    if write_tickets and decisions["confirmed"]:
        tickets = generate_tickets(
            run,
            decisions["confirmed"],
            out_dir,
            use_gemini=use_gemini,
            call_log=call_log,
            on_ticket=lambda t: _emit("ticket", t),
        )
        # Recompute gemini_summary so Carbon ticket tokens/calls are included
        gemini_summary = summarize_calls(call_log)
        run["gemini_usage"] = gemini_summary
        total_duration = round(time.perf_counter() - t_run0, 2)
        run["total_duration_s"] = total_duration

    for c in call_log:
        _log(
            f"GEMINI op={c['op']} model={c['model']} ok={c['ok']} "
            f"latency={c['latency_s']}s in={c.get('input_tokens', 0)} "
            f"out={c.get('output_tokens', 0)} total={c.get('total_tokens', 0)}"
            + (f" err={c['error']}" if c.get("error") else "")
        )
    _log(
        f"Done in {total_duration}s: steps={len(run['steps'])} "
        f"confirmed={len(decisions['confirmed'])} needs_human={len(decisions['needs_human'])} "
        f"dropped={len(decisions['dropped'])} tickets={len(tickets)} gemini_calls={gemini_summary['calls']} "
        f"tokens={gemini_summary['total_tokens']}"
    )

    findings_payload = {
        "run_id": run_id,
        "url": url,
        "confirmed": decisions["confirmed"],
        "needs_human": decisions["needs_human"],
        "dropped": decisions["dropped"],
        "findings": decisions["findings"],
        "tickets": tickets,
        "axe": axe_res,
        "manifest": manifest,
        "gemini_usage": gemini_summary,
        "duration_s": total_duration,
    }
    (out_dir / "steps.json").write_text(json.dumps(run, indent=2), encoding="utf-8")
    (out_dir / "checks.json").write_text(json.dumps(raw_checks, indent=2), encoding="utf-8")
    (out_dir / "findings.json").write_text(json.dumps(findings_payload, indent=2), encoding="utf-8")
    (out_dir / "axe.json").write_text(json.dumps(axe_res, indent=2), encoding="utf-8")
    (out_dir / "run.log").write_text("\n".join(log_lines) + "\n", encoding="utf-8")

    done_payload = {
        "run_id": run_id,
        "status": "ok",
        "stop_reason": run["stop_reason"],
        "steps": len(run["steps"]),
        "confirmed": len(decisions["confirmed"]),
        "needs_human": len(decisions["needs_human"]),
        "dropped": len(decisions["dropped"]),
        "tickets": len(tickets),
        "axe_violations": axe_res["violation_count"],
        "manifest": manifest,
        "duration_s": total_duration,
        "gemini_usage": gemini_summary,
    }
    _emit("done", done_payload)
    return {
        "run_id": run_id,
        "out_dir": str(out_dir),
        "run": run,
        "checks": raw_checks,
        "decisions": decisions,
        "tickets": tickets,
        "axe": axe_res,
        "manifest": manifest,
        "gemini_usage": gemini_summary,
        "duration_s": total_duration,
    }


def main() -> None:
    """Preflight, keyboard run, code checks, and optional Phase 3/4 scoring, injection and axe-core."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--tabs", type=int, default=config.MAX_TABS)
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--score", action="store_true", help="Run Hydrogen reader + Decisions API scorer + decide.py")
    ap.add_argument("--inject", default=None, help="Inject one bug (hide_focus|keyboard_trap|covering_banner|positive_tabindex|label_mismatch|random)")
    ap.add_argument("--seed", type=int, default=None, help="RNG seed for --inject")
    args = ap.parse_args()

    if args.score or args.inject:
        res = run_audit(
            args.url,
            headless=args.headless,
            max_tabs=args.tabs,
            inject=args.inject,
            seed=args.seed,
            use_gemini=args.score,
        )
        if res.get("status") == "blocked":
            print(f"Preflight: blocked — {res['reason']}")
            return
        run = res["run"]
        dec = res["decisions"]
        gu = res["gemini_usage"]
        axe = res["axe"]
        if res.get("manifest"):
            m = res["manifest"]
            print(f"Injected: {m['bug_type']} seed={m['seed']} target={m['target_selector']} ({m['target_text']!r})")
        print(
            f"\nFinished in {res['duration_s']}s ({len(run['steps'])} steps, stop={run['stop_reason']}, "
            f"gemini_calls={gu['calls']}, tokens={gu['total_tokens']})"
        )
        for label, group in (("CONFIRMED", dec["confirmed"]), ("NEEDS_HUMAN", dec["needs_human"])):
            for f in group:
                fp = f["scorer_fail_p"]
                fp_s = f"fail_p={fp:.2f}" if fp is not None else "code-only"
                print(
                    f"  {label:<11} {f['check']:<18} WCAG {f['wcag']:<6} "
                    f"step {f['evidence'].get('step', '-')} ({fp_s}): {f['detail']}"
                )
        print(f"  Dropped scorer evaluations: {len(dec['dropped'])}")
        print(f"  axe-core: {axe['violation_count']} violations (mapped_bugs={axe['mapped_bugs']})")
        print(f"Saved to {res['out_dir']}")
        return

    from playwright.sync_api import sync_playwright

    from blindspot.browser import launch_browser
    from blindspot.checks import run_checks
    from blindspot.preflight import dismiss_banner, run_preflight

    host = urlparse(args.url).netloc.replace("www.", "") or "local"
    run_id = f"{datetime.now():%Y%m%d-%H%M%S}-{host}"
    out_dir = ROOT / "runs" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = launch_browser(p, headless=args.headless)
        try:  # the screen recording is optional evidence; it needs `playwright install ffmpeg`
            context = browser.new_context(viewport={"width": 1280, "height": 800},
                                          record_video_dir=str(out_dir / "video"))
            page = context.new_page()
        except Exception as exc:
            print(f"Video recording off ({str(exc).splitlines()[0][:80]})")
            context = browser.new_context(viewport={"width": 1280, "height": 800})
            page = context.new_page()
        pre = run_preflight(page, args.url)
        print(f"Preflight: {pre.status} {pre.reason} (focusable: {pre.tabbable}, banner: {pre.banner_action})")
        if pre.status != "ok":
            context.close()
            browser.close()
            return
        late = dismiss_banner(page)  # popups that appear after load (e-mail sign-ups, surveys)
        if late != "none":
            print(f"Late popup: clicked {late}")
            page.wait_for_timeout(500)
        run = run_keyboard(page, out_dir, max_tabs=args.tabs, on_step=_print_step, dismiss_popup=dismiss_banner)
        run["late_banner_action"] = late
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
