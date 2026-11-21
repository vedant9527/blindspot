"""All Gemini calls live here (Hydrogen, Decisions API, Argon, Carbon).

Built at the event. Phase 1 adds the client and the Decisions API helper;
Phase 3 adds step reading and scoring (see docs/SPEC.md section 5).
"""

from __future__ import annotations

import base64
import os
import time
from typing import Any

from dotenv import load_dotenv
from google import genai

from blindspot import config

load_dotenv()


def get_client(backup: bool = False) -> genai.Client:
    """Gemini client on the v1beta API (needed for the Decisions API)."""
    key = os.getenv("GEMINI_API_KEY_BACKUP" if backup else "GEMINI_API_KEY")
    if not key:
        raise RuntimeError("Set GEMINI_API_KEY in .env (copy .env.example).")
    return genai.Client(api_key=key, http_options={"api_version": "v1beta"})


def image_block(png_bytes: bytes) -> dict[str, Any]:
    """A Decisions/Interactions image content block from PNG bytes."""
    return {"type": "image", "data": base64.b64encode(png_bytes).decode("ascii"), "mime_type": "image/png"}


def decide(inputs: list[dict[str, Any]] | str, questions: dict[str, dict[str, Any]],
           model: str = config.DECISION_MODEL) -> tuple[Any, float]:
    """One Decisions API call. Returns (response, latency_seconds).

    Response shape (from the SDK): response.answers[question_id] with
    .type ("noul" | "choice" | "score"), .confidence, and .noul (probability of
    true) for yes/no, .choice and .probabilities for choice, .score and
    .probabilities for score.
    """
    last_exc: Exception | None = None
    keys = [False] + ([True] if os.getenv("GEMINI_API_KEY_BACKUP") else [])
    for backup in keys:
        client = get_client(backup=backup)
        for name in (model, f"models/{model}"):
            try:
                t0 = time.perf_counter()
                resp = client.decisions.create(model=name, input=inputs, questions=questions)
                return resp, time.perf_counter() - t0
            except Exception as exc:  # try the other model name / backup key
                last_exc = exc
    raise RuntimeError(f"Decisions API call failed: {last_exc}")
