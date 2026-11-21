"""Decision rule: combine code checks and Gemini Decisions scores honestly.

Built at the event. See docs/SPEC.md section 6 and AGENTS.md rule #2:
- Confirmed: `proven` is True; OR scorer failing probability >= CONFIRM_P AND
  code flagged a suspect for the same (step, check).
- Needs a human: scorer is between HUMAN_LOW and CONFIRM_P, OR scorer flags a
  failure (>= CONFIRM_P) that code cannot support, OR code flagged a suspect
  that scorer did not confirm.
- Dropped: scorer < HUMAN_LOW and no code flag, OR replay fails to reproduce.
- One finding per (check, selector); keep the highest-evidence step.
"""

from __future__ import annotations

from typing import Any

from blindspot import config

# Maps each Decisions API question ID to (check_name, wcag_criterion, failing_when_true)
QUESTION_TO_CHECK: dict[str, tuple[str, str, bool]] = {
    "focus_visible": ("focus_not_visible", "2.4.7", False),
    "focus_covered": ("focus_obscured", "2.4.11", True),
    "label_matches": ("label_in_name", "2.5.3", False),
    "indicator_faint": ("indicator_contrast", "1.4.11", True),
    "order_logical": ("focus_order", "2.4.3", False),
}

CHECK_TO_WCAG: dict[str, str] = {
    "keyboard_trap": "2.1.2",
    "focus_not_visible": "2.4.7",
    "focus_obscured": "2.4.11",
    "focus_order": "2.4.3",
    "label_in_name": "2.5.3",
    "indicator_contrast": "1.4.11",
}


def is_under_overlay(step: dict[str, Any]) -> bool:
    """True if focus is inside an overlay or covered at any sample point by another layer."""
    if step.get("in_overlay"):
        return True
    ob = step.get("obscured") or {}
    return int(ob.get("covered", 0) or 0) > 0


def filter_checks_for_scoring(
    checks: list[dict[str, Any]],
    steps_by_index: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Drop noisy `indicator_contrast` suspects when the focused element is under an overlay."""
    filtered: list[dict[str, Any]] = []
    for c in checks:
        if c["check"] == "indicator_contrast" and not c.get("proven"):
            step_idx = (c.get("evidence") or {}).get("step")
            step = steps_by_index.get(step_idx) if step_idx is not None else None
            if step and is_under_overlay(step):
                continue
        filtered.append(c)
    return filtered


def failing_probability(question_id: str, answer: dict[str, Any] | None) -> float | None:
    """Return the probability (0.0-1.0) of the WCAG-failing answer for `question_id`."""
    if not answer or question_id not in QUESTION_TO_CHECK:
        return None
    if answer.get("type") != "noul" or "noul" not in answer:
        return None
    _, _, fail_when_true = QUESTION_TO_CHECK[question_id]
    p_true = float(answer["noul"])
    return round(p_true if fail_when_true else (1.0 - p_true), 4)


def decide_one(
    *,
    proven: bool,
    suspect: bool,
    fail_p: float | None,
    replayed: bool | None = None,
    confirm_p: float = config.CONFIRM_P,
    human_low: float = config.HUMAN_LOW,
) -> tuple[str, str]:
    """Classify a single candidate into `('confirmed' | 'needs_human' | 'dropped', reason)`."""
    if replayed is False:
        return "dropped", "replay failed to reproduce"
    if proven:
        return "confirmed", "proven by code check"
    if suspect:
        if fail_p is not None and fail_p >= confirm_p:
            return "confirmed", f"code suspect + scorer fail_p={fail_p:.2f} >= {confirm_p:.2f}"
        if fail_p is None:
            return "needs_human", "code suspect (no scorer probability)"
        return "needs_human", f"code suspect with scorer fail_p={fail_p:.2f} < {confirm_p:.2f}"
    # No code flag (neither proven nor suspect)
    if fail_p is None or fail_p < human_low:
        p_txt = "none" if fail_p is None else f"{fail_p:.2f}"
        return "dropped", f"no code flag and scorer fail_p={p_txt} < {human_low:.2f}"
    if fail_p >= confirm_p:
        return "needs_human", f"scorer flagged fail_p={fail_p:.2f} >= {confirm_p:.2f} without code support"
    return "needs_human", f"scorer fail_p={fail_p:.2f} between {human_low:.2f} and {confirm_p:.2f}"


def _step_evidence(step: dict[str, Any]) -> dict[str, Any]:
    ev: dict[str, Any] = {
        "step": step["index"],
        "selector": step.get("selector"),
        "visible_text": step.get("visible_text", ""),
        "label_text": step.get("label_text", ""),
        "accessible_name": step.get("accessible_name", ""),
        "rect": step.get("rect"),
        "focused_crop": step.get("focused_crop"),
        "unfocused_crop": step.get("unfocused_crop"),
        "boxed_crop": step.get("boxed_crop"),
        "full_screenshot": step.get("full_screenshot"),
    }
    if step.get("reader"):
        ev["reader"] = step["reader"]
    return ev


def _rank_tuple(item: dict[str, Any]) -> tuple[int, int, float, int]:
    status_rank = {"confirmed": 2, "needs_human": 1, "dropped": 0}.get(item["status"], 0)
    proven_rank = 1 if item.get("proven") else 0
    fp = float(item.get("scorer_fail_p") or 0.0)
    step_num = int((item.get("evidence") or {}).get("step") or 9999)
    return (status_rank, proven_rank, fp, -step_num)


def decide_findings(
    run: dict[str, Any],
    code_checks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Combine per-step code checks + Gemini Decisions scores into final findings.

    Collects per-step code checks dynamically so step-specific scorer probabilities
    align with the exact step where code flagged a proven or suspect failure, then
    deduplicates to one finding per `(check, selector)` keeping the highest-evidence step.
    """
    from blindspot.checks import (
        check_focus_not_visible,
        check_focus_obscured,
        check_focus_order,
        check_indicator_contrast,
        check_keyboard_trap,
        check_label_in_name,
    )

    steps = run.get("steps") or []
    steps_by_idx: dict[int, dict[str, Any]] = {s["index"]: s for s in steps if "index" in s}

    # Index all per-step and run-level code checks by (step_index_or_None, check_name)
    per_step_code: dict[tuple[int | None, str], dict[str, Any]] = {}
    if code_checks is not None:
        # Start from caller-provided checks (respecting overlay filter), plus per-step checks for alignment
        for c in filter_checks_for_scoring(code_checks, steps_by_idx):
            sidx = (c.get("evidence") or {}).get("step")
            per_step_code[(sidx, c["check"])] = c
    else:
        trap = check_keyboard_trap(run)
        if trap:
            per_step_code[((trap.get("evidence") or {}).get("step"), "keyboard_trap")] = trap
        for oc in check_focus_order(run):
            per_step_code[((oc.get("evidence") or {}).get("step"), "focus_order")] = oc

    # Ensure every individual step's own code check is indexed so scorer agreement on step k matches step k
    for s in steps:
        if s.get("body"):
            continue
        sidx = s["index"]
        for fn in (check_focus_not_visible, check_focus_obscured, check_label_in_name, check_indicator_contrast):
            r = fn(s)
            if not r:
                continue
            if r["check"] == "indicator_contrast" and not r["proven"] and is_under_overlay(s):
                continue
            existing = per_step_code.get((sidx, r["check"]))
            if existing is None or (r["proven"] and not existing["proven"]):
                per_step_code[(sidx, r["check"])] = r

    candidates: list[dict[str, Any]] = []
    seen_pairs: set[tuple[int | None, str]] = set()

    # 1. Evaluate every (step, question) scored by the Decisions API
    for s in steps:
        if s.get("body"):
            continue
        sidx = s["index"]
        answers = ((s.get("scores") or {}).get("answers")) or {}
        for qid, (check_name, wcag, _) in QUESTION_TO_CHECK.items():
            if qid not in answers:
                continue
            if check_name == "indicator_contrast" and is_under_overlay(s):
                continue
            fp = failing_probability(qid, answers[qid])
            code_hit = per_step_code.get((sidx, check_name))
            seen_pairs.add((sidx, check_name))
            proven = bool(code_hit and code_hit.get("proven"))
            suspect = bool(code_hit and code_hit.get("suspect"))
            replayed = (code_hit or {}).get("replayed")
            status, reason = decide_one(proven=proven, suspect=suspect, fail_p=fp, replayed=replayed)
            ev = dict(code_hit["evidence"]) if code_hit else _step_evidence(s)
            if s.get("boxed_crop") and not ev.get("boxed_crop"):
                ev["boxed_crop"] = s["boxed_crop"]
            if s.get("reader") and not ev.get("reader"):
                ev["reader"] = s["reader"]
            detail = (
                code_hit["detail"]
                if code_hit
                else f"Scorer question '{qid}' reported failing probability {fp:.2f} on {s.get('selector')}"
            )
            candidates.append(
                {
                    "check": check_name,
                    "wcag": wcag,
                    "status": status,
                    "decision_reason": reason,
                    "proven": proven,
                    "suspect": suspect,
                    "scorer_question": qid,
                    "scorer_fail_p": fp,
                    "detail": detail,
                    "evidence": ev,
                }
            )

    # 2. Evaluate any remaining code checks that were not paired with a scorer question
    #    (e.g., keyboard_trap, positive_tabindex focus_order, or runs without Gemini scoring)
    for (sidx, check_name), code_hit in per_step_code.items():
        if (sidx, check_name) in seen_pairs:
            continue
        proven = bool(code_hit.get("proven"))
        suspect = bool(code_hit.get("suspect"))
        replayed = code_hit.get("replayed")
        status, reason = decide_one(proven=proven, suspect=suspect, fail_p=None, replayed=replayed)
        ev = dict(code_hit.get("evidence") or {})
        step_obj = steps_by_idx.get(sidx) if sidx is not None else None
        if step_obj:
            if step_obj.get("boxed_crop") and not ev.get("boxed_crop"):
                ev["boxed_crop"] = step_obj["boxed_crop"]
            if step_obj.get("reader") and not ev.get("reader"):
                ev["reader"] = step_obj["reader"]
        candidates.append(
            {
                "check": check_name,
                "wcag": code_hit.get("wcag", CHECK_TO_WCAG.get(check_name, "")),
                "status": status,
                "decision_reason": reason,
                "proven": proven,
                "suspect": suspect,
                "scorer_question": None,
                "scorer_fail_p": None,
                "detail": code_hit.get("detail", ""),
                "evidence": ev,
            }
        )

    # 3. Deduplicate active findings (`confirmed` / `needs_human`) by (check, selector),
    #    keeping the highest-evidence step. Keep `dropped` separately for diagnostics/audit.
    best_active: dict[tuple[str, str], dict[str, Any]] = {}
    dropped: list[dict[str, Any]] = []
    for item in candidates:
        if item["status"] == "dropped":
            dropped.append(item)
            continue
        sel_key = str((item.get("evidence") or {}).get("selector") or item["detail"])
        key = (item["check"], sel_key)
        cur = best_active.get(key)
        if cur is None or _rank_tuple(item) > _rank_tuple(cur):
            best_active[key] = item

    status_order = {"confirmed": 0, "needs_human": 1}
    active = sorted(
        best_active.values(),
        key=lambda f: (status_order.get(f["status"], 2), (f.get("evidence") or {}).get("step") or 0),
    )
    confirmed = [f for f in active if f["status"] == "confirmed"]
    needs_human = [f for f in active if f["status"] == "needs_human"]
    return {
        "confirmed": confirmed,
        "needs_human": needs_human,
        "dropped": dropped,
        "findings": active,
    }
