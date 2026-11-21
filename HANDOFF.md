# Handoff

Read AGENTS.md first. This file says where the build stands.

## Done and verified

- **Phase 0:** repo layout, FastAPI app (`app/main.py`) serving `/` (placeholder) and `/submit` (stranger URL form that appends to `eval/submissions.jsonl`), `requirements.txt`, `.env.example`, `.gitignore`, MIT license, `blindspot/config.py` with all thresholds and model IDs, axe-core 4.14.1 in `vendor/axe.min.js`. `pytest -q` passes.
- **Phase 1 code:**
  - `blindspot/browser.py`: `launch_browser` (Chrome, else Chromium; headed by default), `focus_info` (selector, tag, rect, visible text, tabindex, plus computed accessible name and role from the CDP accessibility tree). Verified on a local page: names and roles come back correctly.
  - `blindspot/preflight.py`: `run_preflight` (load, block detection, banner handling in reject, close, accept order, focusable count). Verified on local pages: a normal page passes and clicks "Reject all"; a "Just a moment / Checking your browser" page is blocked; a password page is blocked.
  - `blindspot/gemini.py`: `get_client` (v1beta), `image_block`, `decide` (tries the primary then backup key, and both model name forms). Verified the Decisions API and Managed Agents requests reach Google (rejected only for a fake key).
  - Scripts: `check_pages.py`, `spike_runner.py`, `spike_models.py`, `spike_decisions.py`, `spike_agent.py`.

- **Prompt A (Claude Code, Nov 21 at the event):**
  - `pytest -q` passes (1 test) on Python 3.12.2 in `.venv`.
  - Git repo initialised, `.env` not tracked, pushed to the public repo https://github.com/vedant9527/blindspot (branch `main`). Commits use the GitHub noreply address set in the repo's local git config.
  - `python scripts/check_pages.py` (headed Chrome, 3 loads each): 18 of 20 pages passed and are in `eval/pages_ok.txt`; per-try details in `eval/pages_check.json`. Blocked: zocdoc.com and goodrx.com (HTTP 403 every load). No workarounds added; they simply drop out. Banner actions: medlineplus, nyulangone, kp.org clicked close; mayoclinic clicked reject; hopkinsmedicine only had accept (`#onetrust-accept-btn-handler`), logged as a last resort.
  - `python scripts/spike_runner.py --url https://www.medicare.gov/ --tabs 10` works: steps 1-9 return correct roles and accessible names from CDP. Step 10 landed on an unnamed `<div>` (role generic) at (-696,-870), off screen: a real candidate for focus_not_visible / focus_order once checks exist. Steps saved to `runs/spike/steps.json` (gitignored).
  - `qrcode[pil]` added to requirements. The app runs in the background with `uvicorn app.main:app --host 0.0.0.0 --port 8000`; `/api/health` returns `{"status":"ok"}`. Stranger form: `http://172.16.249.56:8000/submit` (venue Wi-Fi IP, may change), QR at `eval/submit_qr.png`. If venue Wi-Fi blocks device-to-device traffic, phones cannot reach it; test from a phone first.

- **Prompt B (Claude Code, Nov 21):** `GEMINI_API_KEY` is in `.env` (not tracked; the backup key is empty).
  - `python scripts/spike_models.py`: `gemini-4-hydrogen`, `gemini-4-argon`, `gemini-4-carbon`, `gemini-decision-1` all FOUND (also visible: `gemini-4-neon`). No config changes needed. A Hydrogen text call returned "OK" in 2.9 s.
  - `python scripts/spike_decisions.py --url https://www.medicare.gov/`: works, saved `docs/decisions_response_example.json` (6 questions: 5 noul and 1 choice `page_state`, which answered "normal" at 0.998).
  - `python scripts/spike_agent.py`: Managed Agent completed in 15.8 s and printed `blindspot ok 3.12.3` (the sandbox runs Python 3.12.3).

## Decisions API: what we measured

- Shape matches the SDK notes below. Noul: `{type, noul, confidence}` with `confidence = max(noul, 1 - noul)`. Choice: `{type, choice, confidence, probabilities}`, where `confidence` equals the chosen option's probability.
- Not in our notes: the response also has a top-level `usage` with `input_tokens_by_modality` (text and image), `total_input_tokens` and `total_output_tokens` (0 for decisions). A full 1280x800 screenshot costs about 1,092 image tokens. Log these from `usage` for the cost-per-page metric.
- Latency: the **first call is about 3 s** (cold start); later calls with a small crop take 0.33 to 0.47 s. Five parallel calls finished in 0.68 s wall time (0.34 to 0.55 s each). For Phase 3: make one warm-up call during preflight, and score steps in a thread pool alongside the Tab loop instead of in series, so 40 steps stay inside the 60-second cap.

## API facts confirmed from the google-genai 3.6 SDK

- Decisions: `client.decisions.create(model=..., input=[blocks] or str, questions={id: question})`. Image block: `{"type": "image", "data": <base64>, "mime_type": "image/png"}`. Text block: `{"type": "text", "text": ...}`.
- Question types: `noul` (`instructions`, optional `criteria` with `true_description` and `false_description`), `choice` (`criteria` maps option ID to description), `score` (`criteria` is a list of level descriptions).
- Response: `resp.answers[id]` with `.type` and `.confidence`. Noul: `.noul` is the probability of true, and confidence is `max(noul, 1 - noul)`. Choice: `.choice` and `.probabilities`. Score: `.score` (expected level), `.probabilities`, `.legend`.
- Managed Agents: `client.interactions.create(agent="antigravity-preview-05-2026", input=..., environment={"type": "remote"})`; result has `.status`, `.output_text`, `.errors`. A newer agent `antigravity-preview-09-2026` also exists in the SDK.

## Next

Prompt B is done. Next: the Handoff prompt in PROMPTS.md (Claude Code), then Prompt 2 (runner, fixtures, code checks) in Antigravity. The first page in `eval/pages_ok.txt` is https://www.medicare.gov/.
