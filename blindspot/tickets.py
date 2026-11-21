"""Carbon tickets and red-box evidence crops for confirmed findings (SPEC section 9).

Built at the event. Writes `runs/<id>/tickets/<n>.md` and `tickets/<n>_evidence.png`
for each confirmed finding, using Gemini 4 Carbon (`blindspot.gemini.write_ticket`)
with a clean deterministic fallback if Gemini is disabled or times out.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from blindspot.gemini import make_boxed_crop, write_ticket

ROOT = Path(__file__).resolve().parent.parent

WCAG_META: dict[str, tuple[str, str, str]] = {
    "keyboard_trap": ("2.1.2 No Keyboard Trap", "Level A", "Critical"),
    "focus_not_visible": ("2.4.7 Focus Visible", "Level AA", "High"),
    "focus_obscured": ("2.4.11 Focus Not Obscured (Minimum)", "Level AA", "High"),
    "focus_order": ("2.4.3 Focus Order", "Level A", "High"),
    "label_in_name": ("2.5.3 Label in Name", "Level A", "High"),
    "indicator_contrast": ("1.4.11 Non-text Contrast", "Level AA", "Medium"),
}

FALLBACK_FIXES: dict[str, str] = {
    "keyboard_trap": "```js\n// Allow Tab and Shift+Tab to leave the component; handle Escape to close modals.\n```",
    "focus_not_visible": "```css\n:focus-visible {\n  outline: 3px solid #1d4ed8;\n  outline-offset: 2px;\n}\n```",
    "focus_obscured": "```css\nhtml {\n  scroll-padding-top: 96px;\n  scroll-padding-bottom: 96px;\n}\n```",
    "focus_order": "```html\n<!-- Remove positive tabindex values; use DOM order or tabindex=\"0\" -->\n<a href=\"...\">Link text</a>\n```",
    "label_in_name": "```html\n<!-- Include the visible label inside aria-label, or remove the conflicting aria-label -->\n<button type=\"button\">Search</button>\n```",
    "indicator_contrast": "```css\n:focus-visible {\n  outline: 3px solid #0b4f9c; /* >= 3:1 contrast against white */\n  outline-offset: 2px;\n}\n```",
}


def _rel_url(path: Path | None) -> str | None:
    if not path:
        return None
    try:
        return "/" + str(path.resolve().relative_to(ROOT.resolve())).replace("\\", "/")
    except Exception:
        return str(path)


def save_evidence_crop(
    finding: dict[str, Any],
    out_dir: Path,
    ticket_num: int,
    viewport_width: int = 1280,
) -> tuple[Path | None, bytes | None]:
    """Create and save `tickets/<n>_evidence.png` with a 3 px red box around the target rect."""
    tickets_dir = out_dir / "tickets"
    tickets_dir.mkdir(parents=True, exist_ok=True)
    ev = finding.get("evidence") or {}
    dest = tickets_dir / f"{ticket_num}_evidence.png"

    # Reuse pre-rendered red-box crop if already built during Phase 3 scoring
    boxed = ev.get("boxed_crop")
    if boxed and Path(boxed).exists():
        data = Path(boxed).read_bytes()
        dest.write_bytes(data)
        return dest, data

    full_path = ev.get("full_screenshot")
    rect = ev.get("rect")
    if full_path and Path(full_path).exists():
        full_bytes = Path(full_path).read_bytes()
        if rect and rect.get("width", 0) * rect.get("height", 0) > 0:
            crop_bytes, boxed_full = make_boxed_crop(full_bytes, rect, viewport_width=viewport_width)
            data = crop_bytes or boxed_full
            dest.write_bytes(data)
            return dest, data
        dest.write_bytes(full_bytes)
        return dest, full_bytes

    focused = ev.get("focused_crop")
    if focused and Path(focused).exists():
        data = Path(focused).read_bytes()
        dest.write_bytes(data)
        return dest, data

    return None, None


def _fallback_markdown(finding: dict[str, Any], url: str, crop_rel: str) -> tuple[str, str]:
    check = finding.get("check", "accessibility_issue")
    wcag_name, level, severity = WCAG_META.get(check, (f"WCAG {finding.get('wcag', '')}", "Level AA", "High"))
    ev = finding.get("evidence") or {}
    step = ev.get("step")
    sel = ev.get("selector") or "(page-level)"
    title = f"{wcag_name}: {check.replace('_', ' ')} on `{sel[:50]}`"
    step_line = f"2. Press `Tab` {step} time(s) to focus `{sel}`." if step else f"2. Inspect `{sel}` in the DOM."
    md = (
        f"# {title}\n\n"
        f"- **WCAG Criterion:** {wcag_name} ({level})\n"
        f"- **Severity:** {severity}\n"
        f"- **Status:** Confirmed\n\n"
        f"## Steps to Reproduce\n"
        f"1. Open `{url}`.\n"
        f"{step_line}\n\n"
        f"## What a Patient Experiences\n"
        f"{finding.get('detail', 'A keyboard or screen-reader patient cannot reliably complete this step.')}\n\n"
        f"## Evidence\n"
        f"- Evidence crop: `{crop_rel or 'n/a'}`\n"
        f"- Step index: `{step if step is not None else 'page-level'}`\n"
        f"- Detail: {finding.get('detail', '')}\n\n"
        f"## Suggested Fix\n"
        f"{FALLBACK_FIXES.get(check, '')}\n"
    )
    return title, md


def generate_tickets(
    run: dict[str, Any],
    confirmed: list[dict[str, Any]],
    out_dir: Path,
    *,
    use_gemini: bool = True,
    max_carbon_tickets: int = 6,
    call_log: list[dict[str, Any]] | None = None,
    on_ticket: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    """Generate red-box evidence crops and Carbon Markdown tickets for confirmed findings."""
    if not confirmed:
        return []
    tickets_dir = out_dir / "tickets"
    tickets_dir.mkdir(parents=True, exist_ok=True)
    url = (run.get("page") or {}).get("url") or (run.get("preflight") or {}).get("final_url") or ""
    vw = ((run.get("page") or {}).get("viewport") or {}).get("width") or 1280
    run_id = run.get("run_id") or out_dir.name

    def _build_one(idx: int, finding: dict[str, Any]) -> dict[str, Any]:
        crop_path, crop_bytes = save_evidence_crop(finding, out_dir, idx, viewport_width=vw)
        crop_rel = _rel_url(crop_path) or ""
        ev = finding.get("evidence") or {}
        step_num = ev.get("step")

        title = ""
        md = ""
        used_carbon = False
        if use_gemini and idx <= max_carbon_tickets:
            try:
                res = write_ticket(
                    finding,
                    url,
                    crop_png=crop_bytes,
                    crop_rel_path=crop_rel,
                    call_log=call_log,
                )
                title = res["title"]
                md = res["markdown"]
                used_carbon = True
            except Exception:
                title, md = _fallback_markdown(finding, url, crop_rel)
        else:
            title, md = _fallback_markdown(finding, url, crop_rel)

        # Ensure metadata footer (crop path + step index) is always present per SPEC section 9
        meta_footer = (
            f"\n\n---\n"
            f"*Blindspot run `{run_id}` · Step `{step_num if step_num is not None else 'page-level'}` · "
            f"Evidence crop: `{crop_rel or 'n/a'}`*\n"
        )
        full_md = md.rstrip() + meta_footer
        ticket_path = tickets_dir / f"{idx}.md"
        ticket_path.write_text(full_md, encoding="utf-8")

        return {
            "run_id": run_id,
            "index": idx,
            "check": finding.get("check"),
            "wcag": finding.get("wcag"),
            "selector": ev.get("selector"),
            "step": step_num,
            "title": title,
            "markdown": full_md,
            "ticket_path": str(ticket_path),
            "ticket_url": _rel_url(ticket_path),
            "crop_path": str(crop_path) if crop_path else None,
            "crop_url": crop_rel or None,
            "used_carbon": used_carbon,
        }

    tickets: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=min(4, len(confirmed))) as pool:
        futs = [pool.submit(_build_one, idx, f) for idx, f in enumerate(confirmed, start=1)]
        for fut in futs:
            t = fut.result()
            tickets.append(t)
            if on_ticket:
                on_ticket(t)
    return tickets
