# Handoff

Read AGENTS.md first. This file says where the build stands.

## Done and verified

- **Phase 0:** repo layout, FastAPI app (`app/main.py`) serving `/` (placeholder) and `/submit` (stranger URL form that appends to `eval/submissions.jsonl`), `requirements.txt`, `.env.example`, `.gitignore`, MIT license, `blindspot/config.py` with all thresholds and model IDs, axe-core 4.14.1 in `vendor/axe.min.js`. `pytest -q` passes.
- **Phase 1 code:**
  - `blindspot/browser.py`: `launch_browser` (Chrome, else Chromium; headed by default), `focus_info` (selector, tag, rect, visible text, tabindex, plus computed accessible name and role from the CDP accessibility tree). Verified on a local page: names and roles come back correctly.
  - `blindspot/preflight.py`: `run_preflight` (load, block detection, banner handling in reject, close, accept order, focusable count). Verified on local pages: a normal page passes and clicks "Reject all"; a "Just a moment / Checking your browser" page is blocked; a password page is blocked.
  - `blindspot/gemini.py`: `get_client` (v1beta), `image_block`, `decide` (tries the primary then backup key, and both model name forms). Verified the Decisions API and Managed Agents requests reach Google (rejected only for a fake key).
  - Scripts: `check_pages.py`, `spike_runner.py`, `spike_models.py`, `spike_decisions.py`, `spike_agent.py`.

## Not done yet (needs a real API key)

- [ ] `python scripts/spike_models.py`: confirm `gemini-4-hydrogen`, `gemini-4-argon`, `gemini-4-carbon`, `gemini-decision-1` exist for the key. If a name differs, update `blindspot/config.py`.
- [ ] `python scripts/spike_decisions.py --url <a vetted page>`: saves `docs/decisions_response_example.json`.
- [ ] `python scripts/spike_agent.py`: Managed Agent hello-world.
- [ ] `python scripts/check_pages.py`: produce `eval/pages_ok.txt` from the candidate list.

## API facts confirmed from the google-genai 3.6 SDK

- Decisions: `client.decisions.create(model=..., input=[blocks] or str, questions={id: question})`. Image block: `{"type": "image", "data": <base64>, "mime_type": "image/png"}`. Text block: `{"type": "text", "text": ...}`.
- Question types: `noul` (`instructions`, optional `criteria` with `true_description` and `false_description`), `choice` (`criteria` maps option ID to description), `score` (`criteria` is a list of level descriptions).
- Response: `resp.answers[id]` with `.type` and `.confidence`. Noul: `.noul` is the probability of true, and confidence is `max(noul, 1 - noul)`. Choice: `.choice` and `.probabilities`. Score: `.score` (expected level), `.probabilities`, `.legend`.
- Managed Agents: `client.interactions.create(agent="antigravity-preview-05-2026", input=..., environment={"type": "remote"})`; result has `.status`, `.output_text`, `.errors`. A newer agent `antigravity-preview-09-2026` also exists in the SDK.

## Next

Run the four "not done yet" commands once a key is in `.env`, then do Prompt 2 in PROMPTS.md (runner, fixtures, code checks).
