"""All Gemini calls live here (Hydrogen, Decisions API, Argon, Carbon).

Built at the event. Wraps every Gemini call with an 8-second timeout, retries,
backup API key fallback, and structured logging of model ID, latency, and token
counts (including the Decisions API `usage` block). See docs/SPEC.md section 5.
"""

from __future__ import annotations

import base64
import io
import json
import math
import os
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any

from dotenv import load_dotenv
from google import genai
from google.genai import types
from PIL import Image, ImageDraw

from blindspot import config

load_dotenv()

_TLS = threading.local()
_LOG_LOCK = threading.Lock()
_CALL_LOG: list[dict[str, Any]] = []

RED_OUTLINE = (220, 38, 38)

PAGE_STATE_QUESTIONS: dict[str, dict[str, Any]] = {
    "page_state": {
        "type": "choice",
        "instructions": "What kind of page is shown in this screenshot?",
        "criteria": {
            "normal": "A normal, usable web page.",
            "bot_check": "A bot check or CAPTCHA, such as 'verify you are human'.",
            "login_wall": "A login or sign-in page blocking the content.",
            "error_page": "An error page, such as access denied or not found.",
            "cookie_banner": "A cookie or consent banner covering most of the page.",
        },
    }
}


def get_client(backup: bool = False, timeout_s: float = config.GEMINI_TIMEOUT_S) -> genai.Client:
    """Gemini client on the v1beta API with per-thread connection reuse and timeout."""
    key = os.getenv("GEMINI_API_KEY_BACKUP" if backup else "GEMINI_API_KEY")
    if not key:
        raise RuntimeError("Set GEMINI_API_KEY in .env (copy .env.example).")
    timeout_ms = int(timeout_s * 1000)
    cache: dict[tuple[bool, int], genai.Client] = getattr(_TLS, "clients", None) or {}
    _TLS.clients = cache
    ck = (backup, timeout_ms)
    if ck not in cache:
        cache[ck] = genai.Client(
            api_key=key,
            http_options={"api_version": "v1beta", "timeout": timeout_ms},
        )
    return cache[ck]


def _record_call(entry: dict[str, Any], call_log: list[dict[str, Any]] | None = None) -> None:
    with _LOG_LOCK:
        _CALL_LOG.append(entry)
        if call_log is not None:
            call_log.append(entry)


def get_call_log() -> list[dict[str, Any]]:
    """Return a copy of all logged Gemini calls in this process."""
    with _LOG_LOCK:
        return list(_CALL_LOG)


def reset_call_log() -> None:
    """Clear the process-level Gemini call log."""
    with _LOG_LOCK:
        _CALL_LOG.clear()


def summarize_calls(calls: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate call count, latencies, and token usage by model."""
    by_model: dict[str, dict[str, Any]] = {}
    total_input = 0
    total_output = 0
    total_tokens = 0
    for c in calls:
        m = c.get("model", "unknown")
        bucket = by_model.setdefault(m, {"calls": 0, "errors": 0, "total_tokens": 0, "latency_s_sum": 0.0})
        bucket["calls"] += 1
        if not c.get("ok", True):
            bucket["errors"] += 1
        bucket["total_tokens"] += int(c.get("total_tokens", 0) or 0)
        bucket["latency_s_sum"] = round(bucket["latency_s_sum"] + float(c.get("latency_s", 0.0) or 0.0), 3)
        total_input += int(c.get("input_tokens", 0) or 0)
        total_output += int(c.get("output_tokens", 0) or 0)
        total_tokens += int(c.get("total_tokens", 0) or 0)
    return {
        "calls": len(calls),
        "input_tokens": total_input,
        "output_tokens": total_output,
        "total_tokens": total_tokens,
        "by_model": by_model,
    }


def image_block(png_bytes: bytes) -> dict[str, Any]:
    """A Decisions/Interactions image content block from PNG bytes."""
    return {"type": "image", "data": base64.b64encode(png_bytes).decode("ascii"), "mime_type": "image/png"}


# ---------- Red-box annotation helpers (Pillow) ----------

def draw_red_box_on_full(
    full_png: bytes,
    rect: dict[str, float],
    viewport_width: int = 1280,
    outset_px: int = config.BOX_OUTSET_PX,
    stroke_px: int = config.RED_BOX_WIDTH_PX,
) -> tuple[bytes, tuple[int, int, int, int] | None]:
    """Draw a red marker rectangle around `rect` (outset so focus rings stay untouched).

    Returns `(annotated_full_png, (x0, y0, x1, y1))` in image pixel coordinates.
    """
    img = Image.open(io.BytesIO(full_png)).convert("RGB")
    w, h = img.size
    scale = w / max(1, viewport_width)
    if rect.get("width", 0) * rect.get("height", 0) <= 0:
        return full_png, None
    x0 = max(0, math.floor((rect["x"] - outset_px) * scale))
    y0 = max(0, math.floor((rect["y"] - outset_px) * scale))
    x1 = min(w - 1, math.ceil((rect["x"] + rect["width"] + outset_px) * scale))
    y1 = min(h - 1, math.ceil((rect["y"] + rect["height"] + outset_px) * scale))
    if x1 - x0 < 2 or y1 - y0 < 2:
        return full_png, None
    draw = ImageDraw.Draw(img)
    draw.rectangle([x0, y0, x1, y1], outline=RED_OUTLINE, width=max(1, round(stroke_px * scale)))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue(), (x0, y0, x1, y1)


def make_boxed_crop(
    full_png: bytes,
    rect: dict[str, float],
    viewport_width: int = 1280,
    pad_px: int = config.SCORER_CONTEXT_PAD_PX,
) -> tuple[bytes | None, bytes]:
    """Build `(boxed_crop_png, boxed_full_png)` with a 3px red marker box around `rect`."""
    boxed_full, marker_box = draw_red_box_on_full(full_png, rect, viewport_width=viewport_width)
    if marker_box is None:
        return None, boxed_full
    img = Image.open(io.BytesIO(boxed_full))
    w, h = img.size
    scale = w / max(1, viewport_width)
    cx0 = max(0, math.floor((rect["x"] - pad_px) * scale))
    cy0 = max(0, math.floor((rect["y"] - pad_px) * scale))
    cx1 = min(w, math.ceil((rect["x"] + rect["width"] + pad_px) * scale))
    cy1 = min(h, math.ceil((rect["y"] + rect["height"] + pad_px) * scale))
    if cx1 - cx0 < 4 or cy1 - cy0 < 4:
        return None, boxed_full
    buf = io.BytesIO()
    img.crop((cx0, cy0, cx1, cy1)).save(buf, "PNG")
    return buf.getvalue(), boxed_full


# ---------- Decisions API parser & caller ----------

def _as_dict(obj: Any) -> dict[str, Any]:
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    return json.loads(json.dumps(obj, default=str))


def parse_decisions_response(resp: Any) -> dict[str, Any]:
    """Parse a `gemini-decision-1` response (SDK object or raw dict).

    Matches `docs/decisions_response_example.json`:
      - `answers[qid]`:
          - `noul`: `{type, noul (P(true)), p_false (1 - noul), confidence}`
          - `choice`: `{type, choice, confidence, probabilities}`
          - `score`: `{type, score, confidence, probabilities}`
      - `usage`: `{text_input_tokens, image_input_tokens, total_input_tokens,
                  total_output_tokens, total_tokens}`
    """
    raw = _as_dict(resp)
    raw_answers = raw.get("answers") or {}
    answers: dict[str, dict[str, Any]] = {}
    for qid, ans in raw_answers.items():
        qtype = ans.get("type")
        conf = float(ans.get("confidence", 0.0) or 0.0)
        if qtype == "noul":
            p_true = float(ans.get("noul", 0.0) or 0.0)
            answers[qid] = {
                "type": "noul",
                "noul": p_true,
                "p_true": p_true,
                "p_false": max(0.0, min(1.0, 1.0 - p_true)),
                "confidence": conf,
            }
        elif qtype == "choice":
            probs = {str(k): float(v) for k, v in (ans.get("probabilities") or {}).items()}
            answers[qid] = {
                "type": "choice",
                "choice": str(ans.get("choice", "")),
                "confidence": conf,
                "probabilities": probs,
            }
        elif qtype == "score":
            probs = {str(k): float(v) for k, v in (ans.get("probabilities") or {}).items()}
            answers[qid] = {
                "type": "score",
                "score": float(ans.get("score", 0.0) or 0.0),
                "confidence": conf,
                "probabilities": probs,
            }
        else:
            answers[qid] = dict(ans)

    raw_usage = raw.get("usage") or {}
    modality_tokens: dict[str, int] = {}
    for item in raw_usage.get("input_tokens_by_modality") or []:
        mod = str(item.get("modality", "")).lower()
        if mod:
            modality_tokens[mod] = modality_tokens.get(mod, 0) + int(item.get("tokens", 0) or 0)
    total_in = int(raw_usage.get("total_input_tokens", sum(modality_tokens.values())) or 0)
    total_out = int(raw_usage.get("total_output_tokens", 0) or 0)
    total_tok = int(raw_usage.get("total_tokens", total_in + total_out) or 0)

    return {
        "answers": answers,
        "usage": {
            "text_input_tokens": modality_tokens.get("text", 0),
            "image_input_tokens": modality_tokens.get("image", 0),
            "total_input_tokens": total_in,
            "total_output_tokens": total_out,
            "total_tokens": total_tok,
        },
    }


def decide(
    inputs: list[dict[str, Any]] | str,
    questions: dict[str, dict[str, Any]],
    model: str = config.DECISION_MODEL,
    *,
    op: str = "decisions",
    call_log: list[dict[str, Any]] | None = None,
) -> tuple[Any, float]:
    """One Decisions API call with retries, backup key, and usage logging.

    Returns `(response, latency_seconds)`.
    """
    last_exc: Exception | None = None
    keys = [False] + ([True] if os.getenv("GEMINI_API_KEY_BACKUP") else [])
    for backup in keys:
        client = get_client(backup=backup)
        for attempt in range(config.GEMINI_RETRIES):
            for name in (model, f"models/{model}"):
                t0 = time.perf_counter()
                try:
                    resp = client.decisions.create(model=name, input=inputs, questions=questions)
                    latency = time.perf_counter() - t0
                    parsed = parse_decisions_response(resp)
                    usage = parsed["usage"]
                    _record_call(
                        {
                            "ts": datetime.now(timezone.utc).isoformat(),
                            "op": op,
                            "model": model,
                            "latency_s": round(latency, 3),
                            "text_input_tokens": usage["text_input_tokens"],
                            "image_input_tokens": usage["image_input_tokens"],
                            "input_tokens": usage["total_input_tokens"],
                            "output_tokens": usage["total_output_tokens"],
                            "total_tokens": usage["total_tokens"],
                            "backup_key": backup,
                            "attempt": attempt + 1,
                            "ok": True,
                        },
                        call_log=call_log,
                    )
                    return resp, latency
                except Exception as exc:
                    last_exc = exc
                    if "not found" in str(exc).lower() or "404" in str(exc):
                        continue  # try alternate model name form immediately
                    break  # retry on outer attempt loop / backup key
            if attempt + 1 < config.GEMINI_RETRIES:
                time.sleep(0.25 * (attempt + 1))

    _record_call(
        {
            "ts": datetime.now(timezone.utc).isoformat(),
            "op": op,
            "model": model,
            "latency_s": 0.0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "backup_key": bool(keys[-1]),
            "ok": False,
            "error": str(last_exc)[:240],
        },
        call_log=call_log,
    )
    raise RuntimeError(f"Decisions API call failed: {last_exc}")


def score_page_state(
    screenshot_png: bytes,
    *,
    call_log: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Preflight warm-up + secondary `page_state` check on the loaded screenshot."""
    inputs = [
        image_block(screenshot_png),
        {"type": "text", "text": "Classify the overall state of this web page screenshot."},
    ]
    resp, latency = decide(inputs, PAGE_STATE_QUESTIONS, op="preflight_page_state", call_log=call_log)
    parsed = parse_decisions_response(resp)
    ans = parsed["answers"].get("page_state", {})
    return {
        "choice": ans.get("choice", "normal"),
        "confidence": round(float(ans.get("confidence", 0.0)), 4),
        "probabilities": ans.get("probabilities", {}),
        "latency_s": round(latency, 3),
        "usage": parsed["usage"],
    }


# ---------- Generative model helper (Hydrogen / Argon / Carbon) ----------

def _extract_gen_usage(resp: Any) -> dict[str, int]:
    um = getattr(resp, "usage_metadata", None)
    if um is None:
        return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    inp = int(getattr(um, "prompt_token_count", 0) or 0)
    out = int(getattr(um, "candidates_token_count", 0) or 0) + int(getattr(um, "thoughts_token_count", 0) or 0)
    tot = int(getattr(um, "total_token_count", inp + out) or (inp + out))
    return {"input_tokens": inp, "output_tokens": out, "total_tokens": tot}


def _parse_json_object(text: str) -> dict[str, Any]:
    cleaned = (text or "").strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start != -1 and end > start:
        cleaned = cleaned[start : end + 1]
    return json.loads(cleaned)


def generate_content(
    model: str,
    contents: list[Any] | str,
    *,
    json_mode: bool = False,
    op: str = "generate",
    call_log: list[dict[str, Any]] | None = None,
) -> tuple[str, float]:
    """Call `models.generate_content` with timeout, retries, backup key, and token logging."""
    cfg = types.GenerateContentConfig(
        temperature=0.0,
        response_mime_type="application/json" if json_mode else None,
    )
    last_exc: Exception | None = None
    keys = [False] + ([True] if os.getenv("GEMINI_API_KEY_BACKUP") else [])
    for backup in keys:
        client = get_client(backup=backup)
        for attempt in range(config.GEMINI_RETRIES):
            for name in (model, f"models/{model}"):
                t0 = time.perf_counter()
                try:
                    resp = client.models.generate_content(model=name, contents=contents, config=cfg)
                    latency = time.perf_counter() - t0
                    usage = _extract_gen_usage(resp)
                    _record_call(
                        {
                            "ts": datetime.now(timezone.utc).isoformat(),
                            "op": op,
                            "model": model,
                            "latency_s": round(latency, 3),
                            "input_tokens": usage["input_tokens"],
                            "output_tokens": usage["output_tokens"],
                            "total_tokens": usage["total_tokens"],
                            "backup_key": backup,
                            "attempt": attempt + 1,
                            "ok": True,
                        },
                        call_log=call_log,
                    )
                    return resp.text or "", latency
                except Exception as exc:
                    last_exc = exc
                    if "not found" in str(exc).lower() or "404" in str(exc):
                        continue
                    break
            if attempt + 1 < config.GEMINI_RETRIES:
                time.sleep(0.25 * (attempt + 1))

    _record_call(
        {
            "ts": datetime.now(timezone.utc).isoformat(),
            "op": op,
            "model": model,
            "latency_s": 0.0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "backup_key": bool(keys[-1]),
            "ok": False,
            "error": str(last_exc)[:240],
        },
        call_log=call_log,
    )
    raise RuntimeError(f"Gemini {model} ({op}) failed: {last_exc}")


# ---------- Phase 3 step reader & scorer (SPEC section 5) ----------

def read_step(
    crop: bytes | None,
    full_screenshot: bytes,
    *,
    call_log: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Hydrogen reads a step's unannotated crop + full screenshot.

    Returns `{visible_label: str, indicator_visible: bool, notes: str, latency_s: float}`.
    """
    parts: list[Any] = []
    if crop:
        parts.append(types.Part.from_bytes(data=crop, mime_type="image/png"))
    parts.append(types.Part.from_bytes(data=full_screenshot, mime_type="image/png"))
    prompt = (
        "You are reading a keyboard-focus step on a web page. "
        + ("Image 1 is a close-up crop of the currently focused element; Image 2 is the full viewport. "
           if crop else "The image is the full viewport (the focused element may be off-screen). ")
        + "Return ONLY a JSON object with keys: "
          '{"visible_label": "<exact visible text on the focused element, or empty string>", '
          '"indicator_visible": true or false (whether a focus outline, ring, border highlight, or underline is visible on the focused element), '
          '"notes": "<short note if covered by a banner/popup, faint, or off-screen>"}'
    )
    parts.append(prompt)
    text, latency = generate_content(
        config.READER_MODEL,
        parts,
        json_mode=True,
        op="read_step",
        call_log=call_log,
    )
    try:
        obj = _parse_json_object(text)
    except Exception:
        obj = {"visible_label": "", "indicator_visible": False, "notes": text[:160]}
    return {
        "visible_label": str(obj.get("visible_label", "") or "").strip(),
        "indicator_visible": bool(obj.get("indicator_visible", False)),
        "notes": str(obj.get("notes", "") or "").strip()[:240],
        "latency_s": round(latency, 3),
    }


def build_step_questions(
    accessible_name: str,
    *,
    include_label: bool = True,
    include_contrast: bool = True,
    include_order: bool = False,
) -> dict[str, dict[str, Any]]:
    """Build the Decisions API `noul` question set for one keyboard step (SPEC section 5)."""
    safe_name = (accessible_name or "").strip().replace("\n", " ")[:120]
    questions: dict[str, dict[str, Any]] = {
        "focus_visible": {
            "type": "noul",
            "instructions": "Is there a visible focus indicator on the element in the red box?",
            "criteria": {
                "true_description": (
                    "Inside the outer bright-red annotation box (which our tool drew around the target area), "
                    "the web element itself displays a visible keyboard focus outline, ring, border change, or highlight "
                    "(such as a blue, dark, or high-contrast focus ring)."
                ),
                "false_description": (
                    "Inside the outer bright-red annotation box, the element has NO focus ring, outline, or visual "
                    "focus indicator of its own (or the element is off-screen or completely hidden behind another layer). "
                    "Do not count the outer bright-red marker box itself as a focus indicator."
                ),
            },
        },
        "focus_covered": {
            "type": "noul",
            "instructions": "Is the focused element covered by another element such as a banner or popup?",
            "criteria": {
                "true_description": (
                    "A sticky header, fixed promo bar, cookie banner, modal, or other overlapping layer covers "
                    "all or part of the focused element marked by the red box."
                ),
                "false_description": (
                    "The focused element inside the red box is directly visible on the page and not obscured "
                    "by a banner, popup, or overlapping element."
                ),
            },
        },
    }
    if include_label:
        questions["label_matches"] = {
            "type": "noul",
            "instructions": f"Does the visible label text match the announced name: '{safe_name}'?",
            "criteria": {
                "true_description": (
                    f"Either the visible text shown on the element inside the red box is included in or matches "
                    f"the announced accessible name '{safe_name}', or the element is an icon/graphic with no "
                    f"conflicting visible text label."
                ),
                "false_description": (
                    f"The element inside the red box displays visible words to sighted users that are missing from "
                    f"or contradict the announced accessible name '{safe_name}'."
                ),
            },
        }
    if include_contrast:
        questions["indicator_faint"] = {
            "type": "noul",
            "instructions": "Is the focus indicator too faint to see easily?",
            "criteria": {
                "true_description": (
                    "A focus outline or highlight exists on the element inside the red box, but its color barely "
                    "differs from the surrounding background (very low contrast, washed out, below ~3:1) so it is "
                    "hard to see."
                ),
                "false_description": (
                    "Either the element's focus outline has clear, easy-to-see contrast against its surroundings "
                    "(such as a solid blue or black ring on a light background), or there is no focus ring at all."
                ),
            },
        }
    if include_order:
        questions["order_logical"] = {
            "type": "noul",
            "instructions": "Given the previous and current focus positions, is this a logical next step?",
            "criteria": {
                "true_description": (
                    "Moving keyboard focus from the previous position to the element in the red box follows a "
                    "reasonable top-to-bottom, left-to-right, or section-to-section navigation order."
                ),
                "false_description": (
                    "Keyboard focus jumped unexpectedly backward or far upward within the same region out of "
                    "natural reading order."
                ),
            },
        }
    return questions


def score_step(
    crop: bytes | None,
    full_screenshot: bytes,
    context_text: str,
    *,
    accessible_name: str = "",
    include_label: bool = True,
    include_contrast: bool = True,
    include_order: bool = False,
    call_log: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """One Decisions API call scoring WCAG yes/no questions for a keyboard step.

    `crop` and `full_screenshot` should already carry the outer red marker box
    around the target element (`make_boxed_crop`).
    """
    questions = build_step_questions(
        accessible_name,
        include_label=include_label,
        include_contrast=include_contrast,
        include_order=include_order,
    )
    inputs: list[dict[str, Any]] = []
    if crop:
        inputs.append(image_block(crop))
    inputs.append(image_block(full_screenshot))
    inputs.append({"type": "text", "text": context_text})

    resp, latency = decide(inputs, questions, op="score_step", call_log=call_log)
    parsed = parse_decisions_response(resp)
    return {
        "answers": parsed["answers"],
        "usage": parsed["usage"],
        "latency_s": round(latency, 3),
    }
