"""axe-core baseline runner on the same loaded page (SPEC section 8).

Built at the event. Injects vendored `vendor/axe.min.js` (MPL-2.0), enables the
experimental `label-content-name-mismatch` rule alongside standard rules, and
maps axe rule IDs honestly to our five bug categories.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from playwright.sync_api import Page

ROOT = Path(__file__).resolve().parent.parent
AXE_JS_PATH = ROOT / "vendor" / "axe.min.js"

# SPEC section 8: axe has rules for positive_tabindex and label_mismatch;
# it has no rule for hide_focus, keyboard_trap, or covering_banner by design.
AXE_RULE_TO_BUG: dict[str, str] = {
    "tabindex": "positive_tabindex",
    "label-content-name-mismatch": "label_mismatch",
}

AXE_RULE_TO_CHECK: dict[str, str] = {
    "tabindex": "focus_order",
    "label-content-name-mismatch": "label_in_name",
}

RUN_AXE_JS = """
async () => {
  if (typeof window.axe === 'undefined') {
    throw new Error('axe-core did not load onto window.axe');
  }
  return await window.axe.run(document, {
    resultTypes: ['violations'],
    rules: {
      'label-content-name-mismatch': { enabled: true },
    },
  });
}
"""


def run_axe(page: Page) -> dict[str, Any]:
    """Inject `vendor/axe.min.js` into `page` and return violations + category mapping."""
    t0 = time.perf_counter()
    try:
        has_axe = page.evaluate("() => typeof window.axe !== 'undefined'")
        if not has_axe:
            page.add_script_tag(path=str(AXE_JS_PATH))
        raw = page.evaluate(RUN_AXE_JS)
    except Exception as exc:
        return {
            "violations": [],
            "violation_count": 0,
            "mapped_bugs": [],
            "mapped_checks": [],
            "duration_s": round(time.perf_counter() - t0, 2),
            "error": str(exc)[:300],
        }

    violations = []
    mapped_bugs: set[str] = set()
    mapped_checks: set[str] = set()
    for v in raw.get("violations") or []:
        rule_id = v.get("id", "")
        bug_cat = AXE_RULE_TO_BUG.get(rule_id)
        chk_cat = AXE_RULE_TO_CHECK.get(rule_id)
        if bug_cat:
            mapped_bugs.add(bug_cat)
        if chk_cat:
            mapped_checks.add(chk_cat)
        nodes = v.get("nodes") or []
        violations.append(
            {
                "id": rule_id,
                "impact": v.get("impact"),
                "help": v.get("help", ""),
                "helpUrl": v.get("helpUrl", ""),
                "tags": v.get("tags") or [],
                "nodes_count": len(nodes),
                "targets": [n.get("target") for n in nodes[:5]],
                "mapped_bug": bug_cat,
                "mapped_check": chk_cat,
            }
        )

    return {
        "violations": violations,
        "violation_count": len(violations),
        "mapped_bugs": sorted(mapped_bugs),
        "mapped_checks": sorted(mapped_checks),
        "duration_s": round(time.perf_counter() - t0, 2),
    }
