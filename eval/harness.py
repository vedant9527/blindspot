"""Evaluation harness comparing axe, single_gemini, code_only, and blindspot.

Built at the event. See docs/SPEC.md section 11 and docs/PLAN.md Phases 5 & 8.

Usage:
  python eval/harness.py --set dev [--limit 10]
  python eval/harness.py --build-heldout-manifest
  python eval/harness.py --set heldout --set govuk --set w3c_clean
"""

from __future__ import annotations

import argparse
import json
import shutil
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright  # noqa: E402

from blindspot.axe_runner import run_axe  # noqa: E402
from blindspot.browser import launch_browser  # noqa: E402
from blindspot.gemini import baseline_single_call, summarize_calls  # noqa: E402
from blindspot.injector import (  # noqa: E402
    BUG_TO_CHECK,
    BUG_TYPES,
    inject as inject_bug,
    manifest_sha256,
    write_manifest,
)
from blindspot.preflight import dismiss_banner, run_preflight  # noqa: E402
from blindspot.runner import run_audit  # noqa: E402

SYSTEMS = ("axe", "single_gemini", "code_only", "blindspot")

EVAL_DIR = ROOT / "eval"
RESULTS_DIR = EVAL_DIR / "results"
PAGES_OK = EVAL_DIR / "pages_ok.txt"
SUBMISSIONS = EVAL_DIR / "submissions.jsonl"
HELDOUT_MANIFEST = EVAL_DIR / "heldout_manifest.json"

GOVUK_URL = "https://alphagov.github.io/accessibility-tool-audit/test-cases.html"
W3C_CLEAN_URLS = [
    "https://www.w3.org/WAI/demos/bad/after/home.html",
    "https://www.w3.org/WAI/demos/bad/after/news.html",
    "https://www.w3.org/WAI/demos/bad/after/tickets.html",
    "https://www.w3.org/WAI/demos/bad/after/survey.html",
]

# Stable dev pages from eval/pages_ok.txt (never overlap with submissions.jsonl heldout set)
DEFAULT_DEV_PAGES = [
    "https://nyulangone.org/doctors",
    "https://medlineplus.gov/",
    "https://www.va.gov/find-locations/",
    "https://www.cms.gov/",
    "https://www.kp.org/",
]


def _check_caught_injected_bug(
    confirmed: list[dict[str, Any]],
    bug_type: str,
    target_selector: str | None,
) -> tuple[bool, bool]:
    """Return `(category_caught, exact_target_caught)` for `code_only` / `blindspot`."""
    expected_check = BUG_TO_CHECK[bug_type]
    matching = [f for f in confirmed if f.get("check") == expected_check]
    if not matching:
        return False, False
    if not target_selector:
        return True, True
    for f in matching:
        ev = f.get("evidence") or {}
        if ev.get("selector") == target_selector:
            return True, True
        for pos in ev.get("positive_tabindex") or []:
            if pos.get("selector") == target_selector:
                return True, True
        if target_selector in (ev.get("trap_selectors") or []):
            return True, True
    return True, False


def _run_axe_case(url: str, bug_type: str | None, seed: int | None, headless: bool = True) -> dict[str, Any]:
    t0 = time.perf_counter()
    with sync_playwright() as p:
        browser = launch_browser(p, headless=headless)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()
        pre = run_preflight(page, url)
        if pre.status != "ok":
            context.close()
            browser.close()
            return {"status": "blocked", "reason": pre.reason, "duration_s": round(time.perf_counter() - t0, 2)}
        dismiss_banner(page)
        manifest = inject_bug(page, bug_type, seed=seed) if bug_type else None
        axe_res = run_axe(page)
        context.close()
        browser.close()
    dur = round(time.perf_counter() - t0, 2)
    caught = bool(bug_type and bug_type in (axe_res.get("mapped_bugs") or []))
    return {
        "status": "ok",
        "caught": caught,
        "exact_target_caught": caught,
        "confirmed_count": axe_res.get("violation_count", 0),
        "mapped_bugs": axe_res.get("mapped_bugs", []),
        "violations": [v["id"] for v in (axe_res.get("violations") or [])],
        "manifest": manifest,
        "gemini_calls": 0,
        "total_tokens": 0,
        "cost_usd": 0.0,
        "duration_s": dur,
    }


def _run_single_gemini_case(url: str, bug_type: str | None, seed: int | None, headless: bool = True) -> dict[str, Any]:
    t0 = time.perf_counter()
    call_log: list[dict[str, Any]] = []
    with sync_playwright() as p:
        browser = launch_browser(p, headless=headless)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()
        pre = run_preflight(page, url)
        if pre.status != "ok":
            context.close()
            browser.close()
            return {"status": "blocked", "reason": pre.reason, "duration_s": round(time.perf_counter() - t0, 2)}
        dismiss_banner(page)
        manifest = inject_bug(page, bug_type, seed=seed) if bug_type else None
        png = page.screenshot(full_page=True)
        context.close()
        browser.close()
    try:
        sg = baseline_single_call(png, call_log=call_log)
    except Exception as exc:
        sg = {"findings": [], "categories": [], "error": str(exc)[:200]}
    usage = summarize_calls(call_log)
    dur = round(time.perf_counter() - t0, 2)
    caught = bool(bug_type and bug_type in (sg.get("categories") or []))
    return {
        "status": "ok",
        "caught": caught,
        "exact_target_caught": False,
        "confirmed_count": len(sg.get("findings") or []),
        "categories": sg.get("categories", []),
        "findings": sg.get("findings", []),
        "manifest": manifest,
        "gemini_calls": usage["calls"],
        "total_tokens": usage["total_tokens"],
        "cost_usd": usage["estimated_cost_usd"],
        "duration_s": dur,
    }


def _run_runner_case(
    system: str,
    url: str,
    bug_type: str | None,
    seed: int | None,
    headless: bool = True,
) -> dict[str, Any]:
    use_gemini = system == "blindspot"
    res = run_audit(
        url,
        headless=headless,
        inject=bug_type,
        seed=seed,
        use_gemini=use_gemini,
        record_video=False,
        write_tickets=False,
        run_replay=False,
    )
    # Free screenshot/crop PNGs immediately after scoring to protect disk space
    out_dir_str = res.get("out_dir")
    if out_dir_str:
        out_p = Path(out_dir_str)
        for sub in ("steps", "crops", "video"):
            shutil.rmtree(out_p / sub, ignore_errors=True)
    if res.get("status") == "blocked":
        return {"status": "blocked", "reason": res.get("reason", ""), "duration_s": res.get("duration_s", 0.0)}
    dec = res["decisions"]
    confirmed = dec["confirmed"]
    manifest = res.get("manifest")
    gu = res["gemini_usage"]
    cat_caught = False
    exact_caught = False
    if bug_type:
        cat_caught, exact_caught = _check_caught_injected_bug(
            confirmed,
            bug_type,
            (manifest or {}).get("target_selector"),
        )
    return {
        "status": "ok",
        "caught": exact_caught if (manifest and manifest.get("target_selector")) else cat_caught,
        "category_caught": cat_caught,
        "exact_target_caught": exact_caught,
        "confirmed_count": len(confirmed),
        "needs_human_count": len(dec["needs_human"]),
        "confirmed_checks": [f["check"] for f in confirmed],
        "manifest": manifest,
        "gemini_calls": gu["calls"],
        "total_tokens": gu["total_tokens"],
        "cost_usd": gu["estimated_cost_usd"],
        "duration_s": res["duration_s"],
        "out_dir": res.get("out_dir"),
    }


def run_case(
    system: str,
    url: str,
    bug_type: str | None = None,
    seed: int | None = None,
    headless: bool = True,
) -> dict[str, Any]:
    """Run one `(system, url, bug_type, seed)` evaluation case."""
    if system == "axe":
        return _run_axe_case(url, bug_type, seed, headless=headless)
    if system == "single_gemini":
        return _run_single_gemini_case(url, bug_type, seed, headless=headless)
    if system in ("code_only", "blindspot"):
        return _run_runner_case(system, url, bug_type, seed, headless=headless)
    raise ValueError(f"Unknown system {system!r}")


# ---------- Dataset builders ----------

def build_dev_cases(limit: int | None = None) -> list[dict[str, Any]]:
    """Pair stable dev pages with the 5 injected bugs deterministically."""
    cases: list[dict[str, Any]] = []
    idx = 0
    for page_i, url in enumerate(DEFAULT_DEV_PAGES):
        # Assign two distinct bugs per page across 5 pages -> 10 cases (2 per bug type)
        for slot in range(2):
            bug = BUG_TYPES[(page_i * 2 + slot) % len(BUG_TYPES)]
            idx += 1
            cases.append({"set": "dev", "url": url, "bug_type": bug, "seed": 500 + idx})
    return cases[:limit] if limit else cases


def build_heldout_manifest(headless: bool = False) -> tuple[list[dict[str, Any]], str]:
    """Build `eval/heldout_manifest.json` from stranger URLs in `eval/submissions.jsonl`."""
    if not SUBMISSIONS.exists():
        raise RuntimeError(f"No {SUBMISSIONS} found.")
    raw_urls: list[str] = []
    seen: set[str] = set()
    vetted = set()
    if PAGES_OK.exists():
        vetted = {ln.strip().rstrip("/") for ln in PAGES_OK.read_text(encoding="utf-8").splitlines() if ln.strip()}
    for line in SUBMISSIONS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        u = str(rec.get("url", "")).strip()
        norm = u.rstrip("/")
        if u and norm not in seen and norm not in vetted:
            seen.add(norm)
            raw_urls.append(u)

    entries: list[dict[str, Any]] = []
    with sync_playwright() as p:
        browser = launch_browser(p, headless=headless)
        for idx, url in enumerate(raw_urls, start=1):
            bug = BUG_TYPES[(idx - 1) % len(BUG_TYPES)]
            seed = 2000 + idx
            context = browser.new_context(viewport={"width": 1280, "height": 800})
            page = context.new_page()
            pre = run_preflight(page, url)
            if pre.status == "ok":
                dismiss_banner(page)
                m = inject_bug(page, bug, seed=seed)
                entries.append(m)
            else:
                entries.append(
                    {
                        "url": url,
                        "status": "blocked_in_preflight",
                        "reason": pre.reason,
                        "bug_type": bug,
                        "seed": seed,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                )
            context.close()
        browser.close()

    digest = write_manifest(entries, HELDOUT_MANIFEST)
    return entries, digest


def load_cases_for_set(set_name: str, limit: int | None = None) -> list[dict[str, Any]]:
    if set_name == "dev":
        return build_dev_cases(limit=limit)
    if set_name == "w3c_clean":
        cases = [{"set": "w3c_clean", "url": u, "bug_type": None, "seed": None} for u in W3C_CLEAN_URLS]
        return cases[:limit] if limit else cases
    if set_name == "govuk":
        return [{"set": "govuk", "url": GOVUK_URL, "bug_type": None, "seed": None}]
    if set_name == "heldout":
        if not HELDOUT_MANIFEST.exists():
            raise RuntimeError("Run --build-heldout-manifest first to freeze eval/heldout_manifest.json.")
        entries = json.loads(HELDOUT_MANIFEST.read_text(encoding="utf-8"))
        cases = [
            {"set": "heldout", "url": e["url"], "bug_type": e["bug_type"], "seed": e["seed"]}
            for e in entries
            if e.get("status") != "blocked_in_preflight"
        ]
        return cases[:limit] if limit else cases
    raise ValueError(f"Unknown set {set_name!r}")


# ---------- Aggregation & Markdown output ----------

def summarize_results(
    records: list[dict[str, Any]],
    systems: list[str],
    manifest_hash: str | None,
    manifest_blocked: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], str]:
    # Collect dropped/blocked pages (from manifest preflight and from harness runs)
    dropped_pages: dict[tuple[str, str], dict[str, Any]] = {}
    for mb in manifest_blocked or []:
        dropped_pages[("heldout", mb["url"])] = {
            "set": "heldout",
            "url": mb["url"],
            "reason": mb.get("reason", "blocked in manifest preflight"),
            "systems": ["manifest_preflight"],
        }
    for r in records:
        if r.get("status") != "ok":
            k = (r["set"], r["url"])
            entry = dropped_pages.setdefault(
                k,
                {"set": r["set"], "url": r["url"], "reason": r.get("reason") or r.get("error") or r.get("status"), "systems": []},
            )
            if r["system"] not in entry["systems"]:
                entry["systems"].append(r["system"])

    summary: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "heldout_manifest_sha256": manifest_hash,
        "by_system": {},
        "dropped_pages": list(dropped_pages.values()),
        "records": records,
    }

    for sys_name in systems:
        sys_recs = [r for r in records if r["system"] == sys_name and r.get("status") == "ok"]
        inj_recs = [r for r in sys_recs if r.get("bug_type")]
        clean_recs = [r for r in sys_recs if r.get("set") == "w3c_clean"]
        govuk_recs = [r for r in sys_recs if r.get("set") == "govuk"]

        by_bug: dict[str, dict[str, int]] = {b: {"caught": 0, "total": 0} for b in BUG_TYPES}
        for r in inj_recs:
            b = r["bug_type"]
            by_bug[b]["total"] += 1
            if r.get("caught"):
                by_bug[b]["caught"] += 1

        durations = [float(r["duration_s"]) for r in sys_recs]
        calls = [int(r.get("gemini_calls", 0)) for r in sys_recs]
        costs = [float(r.get("cost_usd", 0.0)) for r in sys_recs]

        summary["by_system"][sys_name] = {
            "pages_ok": len(sys_recs),
            "injected_caught": sum(v["caught"] for v in by_bug.values()),
            "injected_total": sum(v["total"] for v in by_bug.values()),
            "by_bug": by_bug,
            "w3c_clean_false_flags": sum(int(r.get("confirmed_count", 0)) for r in clean_recs),
            "w3c_clean_pages": len(clean_recs),
            "govuk_confirmed": sum(int(r.get("confirmed_count", 0)) for r in govuk_recs),
            "median_seconds": round(statistics.median(durations), 2) if durations else 0.0,
            "mean_gemini_calls": round(statistics.mean(calls), 1) if calls else 0.0,
            "mean_cost_usd": round(statistics.mean(costs), 4) if costs else 0.0,
        }

    md_lines = ["# Blindspot Evaluation Results", ""]
    if manifest_hash:
        md_lines.append(f"**Held-out manifest SHA-256:** `{manifest_hash}`")
        md_lines.append("")

    md_lines.extend(
        [
            "| System | Injected Caught | hide_focus | keyboard_trap | covering_banner | positive_tabindex | label_mismatch | W3C Clean False Flags | Median s/page | Gemini Calls/page | Est. Cost/page |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for sys_name in systems:
        s = summary["by_system"][sys_name]
        bb = s["by_bug"]
        ff = f"{s['w3c_clean_false_flags']} ({s['w3c_clean_pages']}p)" if s["w3c_clean_pages"] else "—"
        md_lines.append(
            f"| `{sys_name}` | **{s['injected_caught']}/{s['injected_total']}** | "
            f"{bb['hide_focus']['caught']}/{bb['hide_focus']['total']} | "
            f"{bb['keyboard_trap']['caught']}/{bb['keyboard_trap']['total']} | "
            f"{bb['covering_banner']['caught']}/{bb['covering_banner']['total']} | "
            f"{bb['positive_tabindex']['caught']}/{bb['positive_tabindex']['total']} | "
            f"{bb['label_mismatch']['caught']}/{bb['label_mismatch']['total']} | "
            f"{ff} | {s['median_seconds']:.1f}s | {s['mean_gemini_calls']:.1f} | \\${s['mean_cost_usd']:.4f} |"
        )
    if any(summary["by_system"][sn]["govuk_confirmed"] > 0 for sn in systems) or any(r["set"] == "govuk" for r in records):
        md_lines.extend(["", "## GOV.UK Accessibility Audit Page (Keyboard & Focus Cases)", ""])
        for sn in systems:
            md_lines.append(f"- `{sn}`: {summary['by_system'][sn]['govuk_confirmed']} confirmed/reported")
    if dropped_pages:
        md_lines.extend(
            [
                "",
                "## Dropped / Blocked Pages (Not Counted as Caught or Missed)",
                "",
                "| Set | URL | Reason | Affected |",
                "| --- | --- | --- | --- |",
            ]
        )
        for dp in dropped_pages.values():
            md_lines.append(f"| `{dp['set']}` | {dp['url']} | {dp['reason']} | {', '.join(dp['systems'])} |")
    md_lines.append("")
    return summary, "\n".join(md_lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", dest="sets", action="append", choices=["dev", "heldout", "govuk", "w3c_clean"])
    ap.add_argument("--systems", default=",".join(SYSTEMS))
    ap.add_argument("--limit", type=int, default=None, help="Cap cases per set")
    ap.add_argument("--headed", action="store_true", help="Use visible Chrome instead of headless")
    ap.add_argument("--out-prefix", default="results", help="Output filename stem in eval/results/")
    ap.add_argument("--build-heldout-manifest", action="store_true")
    args = ap.parse_args()

    if args.build_heldout_manifest:
        entries, digest = build_heldout_manifest(headless=not args.headed)
        ok_n = sum(1 for e in entries if e.get("status") != "blocked_in_preflight")
        print(f"Wrote {len(entries)} entries ({ok_n} loadable) to {HELDOUT_MANIFEST}")
        print(f"SHA-256: {digest}")
        return

    sets = args.sets or ["dev"]
    systems = [s.strip() for s in args.systems.split(",") if s.strip()]
    headless = not args.headed

    all_cases: list[dict[str, Any]] = []
    for sname in sets:
        all_cases.extend(load_cases_for_set(sname, limit=args.limit))

    records: list[dict[str, Any]] = []
    for idx, case in enumerate(all_cases, start=1):
        print(f"\n[{idx}/{len(all_cases)}] set={case['set']} url={case['url']} bug={case['bug_type']} seed={case['seed']}", flush=True)
        for sys_name in systems:
            try:
                res = run_case(sys_name, case["url"], case["bug_type"], case["seed"], headless=headless)
            except Exception as exc:
                res = {"status": "error", "reason": f"{type(exc).__name__}: {str(exc)[:180]}", "duration_s": 0.0}
            rec = {"system": sys_name, **case, **res}
            records.append(rec)
            print(
                f"  {sys_name:<14} status={res.get('status')} caught={res.get('caught', '-')} "
                f"confirmed={res.get('confirmed_count', '-')} dur={res.get('duration_s')}s "
                f"calls={res.get('gemini_calls', 0)}",
                flush=True,
            )

    m_hash = manifest_sha256(HELDOUT_MANIFEST) if HELDOUT_MANIFEST.exists() else None
    manifest_blocked = []
    if "heldout" in sets and HELDOUT_MANIFEST.exists():
        manifest_blocked = [
            e for e in json.loads(HELDOUT_MANIFEST.read_text(encoding="utf-8"))
            if e.get("status") == "blocked_in_preflight"
        ]
    summary, md = summarize_results(records, systems, m_hash, manifest_blocked=manifest_blocked)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = RESULTS_DIR / f"{args.out_prefix}.json"
    md_path = RESULTS_DIR / f"{args.out_prefix}.md"
    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    md_path.write_text(md, encoding="utf-8")
    print(f"\n{md}")
    print(f"Saved {json_path} and {md_path}")


if __name__ == "__main__":
    main()
