"""Gemini Managed Agent replay runner (SPEC section 10, gated at 2:30).

Sends self-contained `blindspot/replay.py` and finding arguments to Google's
remote Managed Agent sandbox (`antigravity-preview-05-2026`). Never runs on the
live demo critical path; executes in the background and marks findings
`replayed: true | false | "unavailable"`.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from blindspot import config
from blindspot.gemini import get_client

ROOT = Path(__file__).resolve().parent.parent
REPLAY_SCRIPT = ROOT / "blindspot" / "replay.py"


def _parse_json_line(text: str) -> dict[str, Any] | None:
    cleaned = (text or "").strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    # Search from the end for a JSON object containing "reproduced"
    for line in reversed(cleaned.splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                obj = json.loads(line)
                if isinstance(obj, dict) and "reproduced" in obj:
                    return obj
            except Exception:
                pass
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start != -1 and end > start:
        try:
            obj = json.loads(cleaned[start : end + 1])
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
    return None


def replay_in_managed_agent(
    url: str,
    tabs: int,
    check: str,
    *,
    manifest: dict[str, Any] | None = None,
    timeout_s: float = 240.0,
) -> dict[str, Any]:
    """Run `replay.py` inside Google's Managed Agent sandbox and return `{replayed, detail, latency_s}`."""
    script_src = REPLAY_SCRIPT.read_text(encoding="utf-8")
    manifest_part = ""
    cmd_extra = ""
    if manifest:
        manifest_json = json.dumps(manifest)
        manifest_part = f"\n2. Save this JSON to `manifest.json`:\n```json\n{manifest_json}\n```\n"
        cmd_extra = " --inject-manifest manifest.json"

    prompt = (
        "Do the following in your remote Linux sandbox:\n"
        "1. Save the Python script below as `replay.py`.\n"
        f"{manifest_part}"
        "3. Install `playwright` and its Chromium browser (`pip install -q playwright && playwright install chromium`).\n"
        f"4. Run: `python3 replay.py --url {url!r} --tabs {int(tabs)} --check {check!r}{cmd_extra}`\n"
        "5. Return ONLY the single JSON output line printed by `replay.py`, nothing else.\n\n"
        f"```python\n{script_src}\n```"
    )

    client = get_client(timeout_s=timeout_s)
    t0 = time.perf_counter()
    try:
        interaction = client.interactions.create(
            agent=config.MANAGED_AGENT,
            input=prompt,
            environment={"type": "remote"},
        )
        elapsed = round(time.perf_counter() - t0, 2)
    except Exception as exc:
        return {
            "replayed": "unavailable",
            "reproduced": None,
            "detail": f"Managed Agent request failed: {str(exc)[:200]}",
            "latency_s": round(time.perf_counter() - t0, 2),
        }

    status = getattr(interaction, "status", "unknown")
    output = getattr(interaction, "output_text", "") or ""
    errors = getattr(interaction, "errors", None)
    parsed = _parse_json_line(output)
    if parsed and "reproduced" in parsed:
        detail = str(parsed.get("detail", ""))
        if any(tok in detail.lower() for tok in ("err_name_not_resolved", "net::err", "timeout", "replay error")):
            return {
                "replayed": "unavailable",
                "reproduced": False,
                "detail": detail,
                "status": status,
                "latency_s": elapsed,
            }
        return {
            "replayed": bool(parsed["reproduced"]),
            "reproduced": bool(parsed["reproduced"]),
            "detail": detail,
            "status": status,
            "latency_s": elapsed,
        }
    return {
        "replayed": "unavailable",
        "reproduced": None,
        "detail": f"Unparseable agent output (status={status}, errors={errors}): {output[:240]}",
        "status": status,
        "latency_s": elapsed,
    }


REPLAYABLE_CHECKS = {"focus_not_visible", "keyboard_trap", "focus_obscured", "focus_order", "label_in_name"}


def start_background_replays(
    run_id: str,
    url: str,
    confirmed: list[dict[str, Any]],
    out_dir: Path,
    *,
    manifest: dict[str, Any] | None = None,
    max_replays: int = 3,
) -> None:
    """Spawn background Managed Agent replay jobs for confirmed findings without blocking the run.

    Updates `out_dir/findings.json` and `out_dir/replays.json` as each sandbox finishes so
    `/api/run/{run_id}` and the UI cards flip to `replayed: true | false | "unavailable"`.
    """
    import threading
    from concurrent.futures import ThreadPoolExecutor

    targets = [
        (idx, f)
        for idx, f in enumerate(confirmed)
        if f.get("check") in REPLAYABLE_CHECKS
    ][:max_replays]
    if not targets:
        return

    file_lock = threading.Lock()
    findings_file = out_dir / "findings.json"
    replays_file = out_dir / "replays.json"

    def _run_one(idx: int, finding: dict[str, Any]) -> dict[str, Any]:
        ev = finding.get("evidence") or {}
        tabs = int(ev.get("step") or 1)
        check = str(finding.get("check") or "")
        use_manifest = manifest if (manifest and manifest.get("expected_check") == check) else None
        res = replay_in_managed_agent(url, tabs, check, manifest=use_manifest)
        record = {
            "finding_index": idx,
            "check": check,
            "selector": ev.get("selector"),
            "step": ev.get("step"),
            **res,
        }
        with file_lock:
            if findings_file.exists():
                data = json.loads(findings_file.read_text(encoding="utf-8"))
                for group_key in ("confirmed", "findings"):
                    for item in data.get(group_key) or []:
                        iev = item.get("evidence") or {}
                        if item.get("check") == check and iev.get("selector") == ev.get("selector"):
                            item["replayed"] = res["replayed"]
                            item["replay_detail"] = res.get("detail", "")
                findings_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
            existing = json.loads(replays_file.read_text(encoding="utf-8")) if replays_file.exists() else []
            existing.append(record)
            replays_file.write_text(json.dumps(existing, indent=2), encoding="utf-8")
        return record

    def _bg() -> None:
        with ThreadPoolExecutor(max_workers=min(3, len(targets))) as pool:
            for idx, f in targets:
                pool.submit(_run_one, idx, f)

    threading.Thread(target=_bg, name=f"replay-{run_id}", daemon=True).start()

