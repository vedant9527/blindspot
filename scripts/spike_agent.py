"""Phase 1 spike: a Managed Agent runs a trivial command in Google's sandbox.

Usage:  python scripts/spike_agent.py

This is slow (often a minute or more). It proves the replay path can work later.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blindspot import config  # noqa: E402
from blindspot.gemini import get_client  # noqa: E402

PROMPT = (
    "Run this shell command in your sandbox and reply with only its output, nothing else: "
    "python3 -c \"import sys; print('blindspot ok', sys.version.split()[0])\""
)


def main() -> None:
    client = get_client()
    t0 = time.perf_counter()
    interaction = client.interactions.create(
        agent=config.MANAGED_AGENT,
        input=PROMPT,
        environment={"type": "remote"},
    )
    elapsed = time.perf_counter() - t0
    print(f"Status: {getattr(interaction, 'status', '?')}  id: {getattr(interaction, 'id', '?')}  in {elapsed:.1f}s")
    print("Output:", getattr(interaction, "output_text", None))
    errors = getattr(interaction, "errors", None)
    if errors:
        print("Errors:", errors)


if __name__ == "__main__":
    main()
