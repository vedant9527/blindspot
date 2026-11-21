"""Code checks: prove what code can prove about each keyboard step.

Built at the event. See docs/SPEC.md section 4. Every check returns
{check, wcag, proven, suspect, evidence, detail}. "proven" means code alone shows
the failure; "suspect" means it needs the scorer or a human. Checks that pass
return None. When in doubt a check says "suspect", never "proven".
"""

from __future__ import annotations

import io
import math
import re
from typing import Any

import numpy as np
from PIL import Image

from blindspot import config

LABEL_ROLES = {"link", "button", "menuitem", "menuitemcheckbox", "menuitemradio", "tab",
               "switch", "option", "treeitem", "checkbox", "radio"}
LABEL_TAGS = {"a", "button", "summary"}
NO_LABEL_TAGS = {"input", "select", "textarea", "iframe"}


# ---------- pixel helpers ----------

def _load(png: bytes) -> np.ndarray:
    return np.asarray(Image.open(io.BytesIO(png)).convert("RGB"), dtype=np.int16)


def _box(rect: dict[str, float], width: int, height: int, scale: float,
         pad: int = config.CROP_PADDING_PX) -> tuple[int, int, int, int] | None:
    x0 = max(0, math.floor((rect["x"] - pad) * scale))
    y0 = max(0, math.floor((rect["y"] - pad) * scale))
    x1 = min(width, math.ceil((rect["x"] + rect["width"] + pad) * scale))
    y1 = min(height, math.ceil((rect["y"] + rect["height"] + pad) * scale))
    if x1 - x0 < 2 or y1 - y0 < 2:
        return None
    return x0, y0, x1, y1


def crop_box(rect: dict[str, float], png: bytes, viewport_width: int) -> tuple[int, int, int, int] | None:
    """Pixel box for the element rect plus padding, clamped to the screenshot. None if off screen."""
    w, h = Image.open(io.BytesIO(png)).size
    return _box(rect, w, h, w / viewport_width)


def crop_png(png: bytes, box: tuple[int, int, int, int]) -> bytes:
    """Crop a PNG to a pixel box."""
    buf = io.BytesIO()
    Image.open(io.BytesIO(png)).crop(box).save(buf, "PNG")
    return buf.getvalue()


def _luminance(rgb) -> float:
    def ch(c: float) -> float:
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(float(v)) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a, b) -> float:
    """WCAG contrast ratio between two RGB colors."""
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def pixel_stats(focused_png: bytes, unfocused_png: bytes, rect: dict[str, float],
                viewport_width: int) -> dict[str, Any] | None:
    """Compare focused and unfocused screenshots around the element.

    Returns mean_diff (0-255) and changed_px inside the crop, changed_elsewhere
    (changed pixels outside the crop) and the contrast between focused and
    unfocused colors of the changed pixels. None if the crop is off screen.
    """
    f, u = _load(focused_png), _load(unfocused_png)
    if f.shape != u.shape:
        return None
    h, w = f.shape[:2]
    scale = w / viewport_width
    box = _box(rect, w, h, scale)
    if box is None:
        return None
    x0, y0, x1, y1 = box
    absdiff = np.abs(f - u)
    changed = absdiff.max(axis=2) > config.PIXEL_DELTA
    crop_changed = changed[y0:y1, x0:x1]
    changed_px = int(crop_changed.sum())
    contrast = None
    if changed_px:
        fc = f[y0:y1, x0:x1][crop_changed].mean(axis=0)
        uc = u[y0:y1, x0:x1][crop_changed].mean(axis=0)
        contrast = round(contrast_ratio(fc, uc), 2)
    area_scale = scale * scale  # report pixel counts in CSS pixels
    return {
        "mean_diff": round(float(absdiff[y0:y1, x0:x1].mean()), 2),
        "changed_px": round(changed_px / area_scale),
        "changed_elsewhere": round((int(changed.sum()) - changed_px) / area_scale),
        "contrast": contrast,
    }


def normalize_label(text: str) -> str:
    """Lowercase and keep only letters and digits (any script)."""
    return "".join(ch for ch in (text or "").lower() if ch.isalnum())


# ---------- checks ----------

def _result(check: str, wcag: str, proven: bool, step: dict[str, Any] | None, detail: str,
            **evidence: Any) -> dict[str, Any]:
    ev: dict[str, Any] = {}
    if step:
        ev = {
            "step": step["index"],
            "selector": step.get("selector"),
            "visible_text": step.get("visible_text", ""),
            "accessible_name": step.get("accessible_name", ""),
            "rect": step.get("rect"),
            "focused_crop": step.get("focused_crop"),
            "unfocused_crop": step.get("unfocused_crop"),
            "full_screenshot": step.get("full_screenshot"),
        }
    ev.update(evidence)
    return {"check": check, "wcag": wcag, "proven": proven, "suspect": not proven, "evidence": ev, "detail": detail}


def _obscured_fully(step: dict[str, Any]) -> bool:
    ob = step.get("obscured") or {}
    return ob.get("sampled", 0) > 0 and ob.get("covered") == ob.get("sampled") == ob.get("fixed_covers")


def check_keyboard_trap(run: dict[str, Any]) -> dict[str, Any] | None:
    """2.1.2: focus stuck on 1-2 elements, and neither Shift+Tab nor Escape gets out."""
    t = run.get("trap_test")
    if not t or run["page"].get("tabbable", 0) < config.TRAP_MIN_TABBABLE:
        return None
    if t["shift_tab_escaped"] or t["escape_key_escaped"]:
        return None
    sel = t["selectors"][0] if t["selectors"] else None
    step = next((s for s in run["steps"] if s.get("selector") == sel), None)
    return _result("keyboard_trap", "2.1.2", True, step,
                   f"Focus stayed on {len(t['selectors'])} element(s) for {config.TRAP_WINDOW} Tab presses; "
                   "Shift+Tab and Escape did not move it away",
                   trap_selectors=t["selectors"], focus_after=t["focus_after"],
                   tabbable=run["page"]["tabbable"])


def check_focus_not_visible(step: dict[str, Any]) -> dict[str, Any] | None:
    """2.4.7: the screen does not change when the element gains focus, or focus is off screen."""
    if step.get("body"):
        return None
    if step.get("offscreen"):
        return _result("focus_not_visible", "2.4.7", True, step,
                       "Focused element is entirely off screen, so the user cannot see where focus is")
    px = step.get("pixels")
    if not px or _obscured_fully(step):  # a fully covered element is reported as focus_obscured
        return None
    if px["changed_px"] < config.FOCUS_CHANGED_PX_MIN:
        if px["changed_elsewhere"] > config.ELSEWHERE_PX_MAX:
            return _result("focus_not_visible", "2.4.7", False, step,
                           "Nothing changes around the element on focus, but the screen changed elsewhere "
                           "(the indicator may be on a parent)", pixels=px)
        return _result("focus_not_visible", "2.4.7", True, step,
                       f"No visible focus indicator: {px['changed_px']} pixels change around the element "
                       "between focused and unfocused", pixels=px)
    if px["mean_diff"] < config.FOCUS_DIFF_MIN:
        return _result("focus_not_visible", "2.4.7", False, step,
                       f"Focus indicator is very faint (mean pixel change {px['mean_diff']})", pixels=px)
    return None


def check_focus_obscured(step: dict[str, Any]) -> dict[str, Any] | None:
    """2.4.11: a fixed or sticky element covers the focused element (all sample points = proven)."""
    ob = step.get("obscured") or {}
    if step.get("body") or not ob.get("sampled") or not ob.get("covered"):
        return None
    if _obscured_fully(step):
        return _result("focus_obscured", "2.4.11", True, step,
                       f"Focused element is entirely hidden behind {', '.join(ob['covering'])} (fixed or sticky)",
                       obscured=ob)
    return _result("focus_obscured", "2.4.11", False, step,
                   f"Focused element is partly covered by {', '.join(ob['covering'])} "
                   f"({ob['covered']} of {ob['sampled']} points)", obscured=ob)


def check_focus_order(run: dict[str, Any]) -> list[dict[str, Any]]:
    """2.4.3: positive tabindex is proven (F44); big upward jumps in one region are suspects."""
    out = []
    pos = run["page"].get("positive_tabindex") or []
    if pos:
        first = pos[0]
        step = next((s for s in run["steps"] if s.get("selector") == first["selector"]), None)
        out.append(_result("focus_order", "2.4.3", True, step,
                           f"{len(pos)} element(s) use a positive tabindex, which reorders keyboard focus "
                           f"(e.g. tabindex={first['tabindex']} on '{first['text'][:40]}')",
                           positive_tabindex=pos))
    prev = None
    for s in run["steps"]:
        if s.get("body") or not s.get("rect"):
            continue
        if prev is not None:
            prev_top = prev["rect"]["y"] + prev["scroll_y"]
            top = s["rect"]["y"] + s["scroll_y"]
            if prev_top - top > config.ORDER_JUMP_PX and s.get("landmark") == prev.get("landmark"):
                out.append(_result("focus_order", "2.4.3", False, s,
                                   f"Focus jumped {prev_top - top:.0f}px up the page from step {prev['index']} "
                                   "within the same region", previous_selector=prev.get("selector")))
        prev = s
    return out


def check_label_in_name(step: dict[str, Any]) -> dict[str, Any] | None:
    """2.5.3: the visible label text is not contained in the accessible name."""
    if step.get("body") or not step.get("ax_ok"):
        return None  # never treat an unreadable name as an empty one
    tag, role = step.get("tag"), step.get("role")
    if tag in NO_LABEL_TAGS or not (tag in LABEL_TAGS or role in LABEL_ROLES):
        return None
    label, name = normalize_label(step.get("label_text", "")), normalize_label(step.get("accessible_name", ""))
    if not label or label in name:
        return None
    return _result("label_in_name", "2.5.3", True, step,
                   f"Visible label '{step['label_text'][:60]}' is not in the accessible name "
                   f"'{step.get('accessible_name', '')[:60]}'", label_text=step["label_text"])


def check_indicator_contrast(step: dict[str, Any]) -> dict[str, Any] | None:
    """1.4.11 (suspect only): focused vs unfocused colors of the indicator differ by less than 3:1."""
    px = step.get("pixels")
    if not px or px.get("contrast") is None or px["changed_px"] < config.FOCUS_CHANGED_PX_MIN:
        return None
    if px["contrast"] >= config.INDICATOR_CONTRAST_MIN:
        return None
    return _result("indicator_contrast", "1.4.11", False, step,
                   f"Focus indicator contrast is {px['contrast']}:1 against the unfocused state", pixels=px)


def run_checks(run: dict[str, Any]) -> list[dict[str, Any]]:
    """All failing and suspect checks for a run, one per (check, selector), proven first."""
    results: list[dict[str, Any]] = []
    trap = check_keyboard_trap(run)
    if trap:
        results.append(trap)
    results.extend(check_focus_order(run))
    for step in run["steps"]:
        for fn in (check_focus_not_visible, check_focus_obscured, check_label_in_name, check_indicator_contrast):
            r = fn(step)
            if r:
                results.append(r)
    best: dict[tuple[str, Any], dict[str, Any]] = {}
    for r in results:
        key = (r["check"], r["evidence"].get("selector") or r["detail"])
        cur = best.get(key)
        if cur is None or (r["proven"] and not cur["proven"]):
            best[key] = r
    return sorted(best.values(), key=lambda r: (not r["proven"], r["evidence"].get("step") or 0))
