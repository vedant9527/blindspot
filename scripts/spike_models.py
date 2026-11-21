"""Phase 1 spike: confirm the API key works and the model names exist.

Usage:  python scripts/spike_models.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blindspot import config  # noqa: E402
from blindspot.gemini import get_client  # noqa: E402


def main() -> None:
    client = get_client()
    wanted = [config.READER_MODEL, config.HARD_CALL_MODEL, config.TICKET_MODEL, config.DECISION_MODEL]
    names = []
    try:
        for m in client.models.list():
            name = getattr(m, "name", "") or ""
            if "gemini-4" in name or "decision" in name:
                names.append(name)
    except Exception as exc:
        print(f"Could not list models: {exc}")
    print("Gemini 4 and decision models visible to this key:")
    for n in sorted(names):
        print("  ", n)
    for w in wanted:
        found = any(n.endswith(w) for n in names)
        print(f"{'FOUND  ' if found else 'MISSING'} {w}")

    print(f"\nQuick text call to {config.READER_MODEL}:")
    try:
        t0 = time.perf_counter()
        resp = client.models.generate_content(model=config.READER_MODEL, contents="Reply with the single word OK.")
        print(f"  {resp.text!r} in {time.perf_counter() - t0:.2f}s")
    except Exception as exc:
        print(f"  failed: {exc}")


if __name__ == "__main__":
    main()
