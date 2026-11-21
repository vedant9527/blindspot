# Handoff

Read AGENTS.md first. This file says where the build stands.

**Status (Nov 21, ~15:38, Google Antigravity):** **THRESHOLDS FROZEN (`blindspot/config.py` locked).** Phase 8 held-out evaluation (`eval/results/results.md`, **Blindspot 12/13, 0 W3C clean false flags**) and Phase 9 final `README.md` are complete (HAR snapshots skipped per plan). Next: demo rehearsal, 1-minute video, and submit by 4:50 PM.
- **Held-out manifest SHA-256:** `816e4bb137338731ce06adaf5d2c76a90c9f2ed9c985b7907332226e606f2492`

Note: restart `uvicorn` when convenient so the live `:8000` server picks up the new `run_replay` background hook (per instructions, port 8000 was not restarted).

## Setup and run (exact commands)

```bash
cd ~/blindspot
source .venv/bin/activate              # Python 3.12; create with: python3 -m venv .venv
pip install -r requirements.txt
playwright install ffmpeg              # screen recordings (already installed on this laptop)
pytest -q                              # 49 tests, ~125 s, headless Chrome
uvicorn app.main:app --host 0.0.0.0 --port 8000     # app + run API + SSE + stranger form at /submit
ipconfig getifaddr en0                 # laptop IP; regenerate eval/submit_qr.png if it changed
python -m blindspot.runner --url https://medlineplus.gov/ --score --inject hide_focus --seed 101
python eval/harness.py --set dev --out-prefix dev_results
```

Keys in `.env` (never commit it; `.env.example` stays blank): `GEMINI_API_KEY` (required, used by every model and the Managed Agent) and `GEMINI_API_KEY_BACKUP` (optional; `blindspot/gemini.py` falls back to it on any error). Suggested: event credits key as primary, the free AI Studio key as backup.

API quirks found so far: the first Decisions API call is ~3 s (cold), later ones ~0.4 s and they parallelise well; responses carry a top-level `usage` block not in the launch docs; the Managed Agent sandbox runs Python 3.12.3 and took 16 s for hello-world.

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

## Phase 2: runner, fixtures, code checks (done, Claude Code, ~11:40)

- `blindspot/runner.py`: `run_keyboard(page, out_dir, max_tabs, timeout_s, on_step, dismiss_popup)` Tabs through a loaded page. Per step it saves the full screenshot (`steps/NN.png`), focused and unfocused crops (`crops/NN_focused.png`, `NN_unfocused.png`; unfocused = after `el.blur()`, then focus is restored), CDP accessible name and role, visible label text (skips aria-hidden and 1px screen-reader text), landmark, coverage samples (`elementFromPoint` at center and four corners) and pixel stats. Stops on cycle, trap (then runs the Shift+Tab and Escape escape test), 40 Tabs or 60 s. Focus starts at the top of the document via a body-focus trick instead of clicking a spot (a click could follow a link).
- CLI: `python -m blindspot.runner --url URL [--headless] [--tabs N]` runs preflight, the keyboard run and the checks; saves `runs/<run_id>/steps.json`, `checks.json`, screenshots, crops and a `.webm` screen recording (needs `playwright install ffmpeg`, already installed here; it falls back to no video if missing).
- `blindspot/checks.py`: `run_checks(run)` returns `{check, wcag, proven, suspect, evidence, detail}` per (check, selector). Proven: keyboard_trap, focus_not_visible (fewer than 8 changed pixels around the element and the screen did not change elsewhere, or focus entirely off screen), focus_obscured (all sample points under a fixed or sticky layer), focus_order (positive tabindex), label_in_name. Suspect only: faint indicators, partial or non-fixed coverage, upward jumps over 300 px in one region, indicator contrast under 3:1.
- Thresholds added to `blindspot/config.py` (PIXEL_DELTA, FOCUS_CHANGED_PX_MIN, ELSEWHERE_PX_MAX, RING_MAX_FRACTION, TRAP_*, MAX_POPUP_CLOSES).
- `fixtures/`: clean, trap, hidden_focus, covered, tabindex, label_mismatch, popup (12 focusable elements each). `pytest -q`: 13 passed (~85 s, headless Chrome), including `test_late_popup_is_closed_and_page_is_tested` proving the runner closes a late `role="dialog"` popup ("Close dialog"), logs it in `run["popups"]`, and then tests all 12 page elements.
- Real pages (headless sweep of original 18 `eval/pages_ok.txt` pages):
  - 12 of 18 completed cleanly in `--headless` mode; 6 (`nih.gov`, `nyc.gov`, `nychealthandhospitals.org`, `hopkinsmedicine.org`, `mayoclinic.org`, `plannedparenthood.org`) were blocked in headless mode (all 6 still pass 3/3 loads in headed Chrome).
  - **Recommended 3 most stable pages for the live demo:**
    1. `https://nyulangone.org/doctors` (0 proven, 3 suspects, 0 mid-run popups, 32.8s)
    2. `https://www.va.gov/find-locations/` (0 proven, 16 suspects, 0 mid-run popups, 24.58s)
    3. `https://medlineplus.gov/` (0 proven, 20 suspects, 0 mid-run popups, 26.5s)
    (Backup: `https://www.kp.org/` — 0 proven, 7 suspects, 26.7s. Avoid `medicare.gov` and `healthcare.gov` for live demos due to random Qualtrics popups.)
- Expanded vetted dev/demo list (`eval/pages_vetted.txt` -> `eval/pages_ok.txt`): added 20 public healthcare pages (appointments, find-a-doctor, billing info, telehealth, state Medicaid, public insurers, community health centers, pharmacy locators). `python scripts/check_pages.py` (headed Chrome, 3 loads each): **37 of 40 passed** and are in `eval/pages_ok.txt` (blocked: `zocdoc.com` HTTP 403, `goodrx.com` HTTP 403, `mountsinai.org/patient-care/billing-and-insurance` only 4 focusable elements). **Dev and demo set only — never mix into the held-out set, which comes only from `eval/submissions.jsonl`.**

### Open issues

- Both `medicare.gov` and `healthcare.gov` show Qualtrics sign-up popups at random, so results differ between runs. Use the 3 stable pages above (or Phase 9 snapshots) for the live demo.
- `indicator_contrast` is noisy (many suspects under dimming layers). It is suspect-only, so it cannot confirm anything without the scorer, but consider not sending it to the scorer when the element is under an overlay.
- Disk space on `/` is low (~3.1 GB free). Avoid running multiple parallel video-recording sweeps; prune old `runs/` folders if needed.
- Phase 3 should parallelise scoring (see the latency notes above): the run takes ~0.6 s per step without Gemini.

## Step 2 (Antigravity + Claude Code review, ~12:20)

- `fixtures/popup.html` + `test_late_popup_is_closed_and_page_is_tested`: a `role="dialog"` popup appears after 1 s; the runner closes it ("close"), logs it in `run["popups"]`, restarts and tests the 12 page elements with no proven findings. Test made timing-proof (ignores every step inside the popup). `pytest -q`: 13 passed.
- Headless batch over `eval/pages_ok.txt` (one run each, all at once):

| Page | Proven | Suspects | Steps | Notes |
| --- | --- | --- | --- | --- |
| mountsinai.org/find-a-doctor | 28 | 39 | 40 | **Real:** an accessibility overlay widget sets `aria-label` on links to its own instruction ("To make this website accessible to screen reader, press combination of alt and 1 keys..."), so 25 links lose their visible name (2.5.3). Verified with a separate CDP probe. 3 focus_not_visible. |
| my.clevelandclinic.org | 1 | 20 | 40 | "Closures & Updates" is announced as "Open notification banner" (2.5.3) |
| cdc.gov | 1 | 30 | 40 | 3 elements with positive tabindex, e.g. tabindex=1 on "Skip to site content" (F44) |
| nyulangone.org/doctors | 0 | 3 | 40 | Quiet page: good base for Break it injections |
| medlineplus.gov | 0 | 20 | 40 | |
| cms.gov | 0 | 38 | 40 | |
| va.gov/find-locations | 0 | 16 | 40 | |
| healthcare.gov, medicare.gov | 0 | 7-8 | 9-16 | No popup this time (they are random) |
| nih.gov, nyc.gov, nychealthandhospitals.org, hopkinsmedicine.org, mayoclinic.org, plannedparenthood.org, kp.org, oscarhealth.com | - | - | - | No result: headless preflight blocked (nih.gov returns HTTP 403 headless, though it passed 3/3 headed) or the batch was cut off |
| w3.org BAD before | - | - | - | Started, cut off mid-run (no steps.json) |

- **Demo pages (recommended, each run once so far; run each twice headed before relying on it):** mountsinai.org/find-a-doctor (real overlay finding), cdc.gov (real positive tabindex), nyulangone.org/doctors (quiet base for injected bugs).
- Open: `python -m blindspot.runner` writes nothing when preflight blocks; it should save a `preflight.json` with the reason so batch runs show why. Run batches headed and one at a time.

## Phase 3: Gemini reading, Decisions API scoring, decision rule & SSE (done, Antigravity, ~12:45)

- `blindspot/config.py`: added `GEMINI_TIMEOUT_S` (8.0s, converted to `8000` ms for `google-genai` `HttpOptions`), `GEMINI_RETRIES` (2), `SCORER_WORKERS` (12), `RED_BOX_WIDTH_PX` (3), `BOX_OUTSET_PX` (8px gap so the red marker box never hides CSS focus outlines), and `SCORER_CONTEXT_PAD_PX` (48px). Existing thresholds untouched.
- `blindspot/gemini.py`:
  - `parse_decisions_response(resp)` written from `docs/decisions_response_example.json`: parses `noul` (`noul` = P(true), `p_false` = 1 - `noul`, `confidence`), `choice`, `score`, and `usage` (`text_input_tokens`, `image_input_tokens`, `total_input_tokens`, `total_output_tokens`, `total_tokens`).
  - Thread-local `genai.Client` cache, 8s timeout, retries, `GEMINI_API_KEY_BACKUP` fallback, and structured per-call logging (`summarize_calls`).
  - `make_boxed_crop`: draws an outer 3px red marker rectangle around `rect + 8px` on the full screenshot and produces `crops/NN_boxed.png`.
  - `score_page_state`: preflight warm-up Decisions API call (`page_state` choice) so step-scoring calls hit a warm endpoint.
  - `read_step` (`gemini-4-hydrogen` JSON `{visible_label, indicator_visible, notes}`) and `score_step` (`gemini-decision-1` `noul` questions with explicit criteria; omits `indicator_faint` when the element is under an overlay; includes `order_logical` only when code flags an upward-jump suspect).
- `blindspot/decide.py`:
  - Implements SPEC section 6: `confirmed` (`proven` or `suspect` + `fail_p >= CONFIRM_P`), `needs_human` (`HUMAN_LOW <= fail_p < CONFIRM_P`, scorer >= `CONFIRM_P` without code support, or unconfirmed code suspect), `dropped` (`fail_p < HUMAN_LOW` with no code flag, or `replayed is False`).
  - Suppresses `indicator_contrast` suspects on steps under an overlay (`is_under_overlay`).
  - Deduplicates active findings to one per `(check, selector)`, keeping the highest-evidence step.
- `blindspot/runner.py` & `app/main.py`:
  - `run_audit(...)` runs preflight (+ warm-up), the Tab loop with a 12-worker `ThreadPoolExecutor` scoring steps concurrently alongside Playwright, `decide_findings`, and writes `steps.json`, `checks.json`, `findings.json`, `crops/NN_boxed.png`, and `run.log`. CLI flag: `--score`.
  - `POST /api/run` (`{url, inject, seed}` -> `{run_id}`), `GET /api/run/{run_id}/events` (SSE streaming `preflight`, `step`, `finding`, `done`, `error`), `GET /api/run/{run_id}`, `GET /api/vetted`, and `/runs` static mount.
- Verified on all 7 fixtures with live `gemini-4-hydrogen` + `gemini-decision-1` (~8.4–11.0s each, ~40k tokens/fixture):
  - `clean.html`: **0 confirmed**, 0 needs_human, 52 dropped.
  - `popup.html`: **0 confirmed**, 0 needs_human, 52 dropped.
  - `trap.html`: **1 confirmed** (`keyboard_trap` 2.1.2), 0 needs_human, 48 dropped.
  - `hidden_focus.html`: **1 confirmed** (`focus_not_visible` 2.4.7, scorer `fail_p=0.93`), 0 needs_human, 51 dropped.
  - `covered.html`: **1 confirmed** (`focus_obscured` 2.4.11, scorer `fail_p=0.77`), 2 needs_human (scorer-only flags on the covered element), 48 dropped.
  - `tabindex.html`: **1 confirmed** (`focus_order` 2.4.3), 0 needs_human, 52 dropped.
  - `label_mismatch.html`: **1 confirmed** (`label_in_name` 2.5.3, scorer `fail_p=0.95`), 0 needs_human, 51 dropped.
- Verified 40-step real-page latency on `https://nyulangone.org/doctors` (`--headless --score`): **52.76s** total (preflight warm-up + 40 Tab steps + 40 Hydrogen calls + 40 Decisions calls = 81 Gemini calls, 121,810 tokens; **0 confirmed**, 13 needs_human, 144 dropped) — inside the 60s hard cap.
- Tests: `tests/test_decide.py` added (parser, `decide_one`, deduplication, overlay gating, end-to-end `/api/run` + SSE). `pytest -q`: **20 passed**.

## Phase 4: bug injector and axe-core baseline (done, Antigravity, ~13:00)

- `blindspot/injector.py`: `inject(page, bug_type, seed)` injects any of the five WCAG bugs (`hide_focus`, `keyboard_trap`, `covering_banner`, `positive_tabindex`, `label_mismatch`, or `"random"`) using `random.Random(seed)`, tags the target with `data-bs-target`, and returns a manifest (`url`, `bug_type`, `expected_check`, `seed`, `target_selector`, `target_text`, `timestamp`). Includes `write_manifest` / `manifest_sha256` for the held-out protocol. Prefers first-viewport early-DOM targets (first 15) so the 40-Tab runner reaches the target even on large pages.
- `blindspot/axe_runner.py`: `run_axe(page)` injects `vendor/axe.min.js`, enables `label-content-name-mismatch` alongside standard rules, and maps `tabindex` -> `positive_tabindex` and `label-content-name-mismatch` -> `label_mismatch` honestly.
- Wired into `run_audit` in `blindspot/runner.py` (CLI `--inject`, `--seed`; writes `manifest.json` and `axe.json`; emits the `axe` SSE event before `done`).
- Tests: `tests/test_injector.py` verifies all 5 bugs + `"random"` + SHA-256 manifest + axe-core honesty on `fixtures/clean.html`. `pytest -q`: **26 passed**.
- Live verification on `https://medlineplus.gov/` (`--headless --score`, seeds 101–105):
  - **Blindspot: 5/5 confirmed** on the exact injected target (`hide_focus` step 11 `fail_p=0.92`, `keyboard_trap` step 4, `covering_banner` step 13 `fail_p=0.82`, `positive_tabindex`, `label_mismatch` step 14 `fail_p=0.92`; 14.3–38.5s each).
  - **axe-core: 2/5 caught** (`positive_tabindex` via `tabindex`, `label_mismatch` via `label-content-name-mismatch`), **3/5 missed** by design (`hide_focus`, `keyboard_trap`, `covering_banner`), plus baseline `landmark-one-main` and `region` violations.

## Phase 5 (pre-freeze): 1:30 gate, baselines, dev-set run & fixes (done, Antigravity, ~13:49)

- **1:30 Gate passed** across all three stable demo pages (`nyulangone.org/doctors` 39.7s, `va.gov/find-locations/` 31.0s, `medlineplus.gov/` 28.1s; all under the 60s cap). Nothing cut.
- `blindspot/gemini.py`: added `baseline_single_call(full_page_screenshot)` (`gemini-4-argon` single-screenshot baseline) and per-model cost estimation in `summarize_calls`. Raised `GEMINI_TIMEOUT_S = 10.0` (the Gemini API rejects `<10s` deadlines with HTTP 400) and `GEMINI_GEN_TIMEOUT_S = 20.0`.
- `eval/harness.py`: runs `axe`, `single_gemini`, `code_only`, and `blindspot` over `dev`, `heldout`, `govuk`, and `w3c_clean`; includes `--build-heldout-manifest` (writes `eval/heldout_manifest.json` from `eval/submissions.jsonl` and prints its SHA-256).
- **Pre-freeze fixes from dev-set inspection (all logged in `failure_log.md`):**
  1. Pierced open `shadowRoot.activeElement` in `browser.py` and `runner.py` (eliminated all 3 Shadow DOM false flags on `va.gov`).
  2. Computed per-changed-pixel WCAG contrast (`strong_ring_px`) and disappearing-border suspect detection (`border_vanished`) in `checks.py` (eliminated large-box / mixed text+ring false flags on `medlineplus.gov` and caught disappearing-border focus loss on `nyulangone.org`).
  3. Locked descendant unfocused borders in `injector.py` `hide_focus`, and swapped `telehealth.hhs.gov` (headless 403) to `kp.org` in `DEFAULT_DEV_PAGES`.
- **10-case `dev` set results (`eval/results/dev_results.md`):**
  - `blindspot`: **10/10** injected bugs caught (exact target matched on all 10; 2/2 per bug category) + confirms genuine <3:1 faint focus rings (e.g. `cms.gov` 2.87:1 tan outline) that `code_only` can only mark suspect; 37.0s median, 72.4 Gemini calls/page, \$0.0340/page.
  - `code_only`: **10/10** injected bugs caught (cannot confirm faint-contrast suspects without the scorer); 29.5s median.
  - `axe`: **4/10** (`2/2 positive_tabindex`, `2/2 label_mismatch`, `0/6` on `hide_focus`, `keyboard_trap`, `covering_banner`); 8.1s median.
  - `single_gemini` (`gemini-4-argon` 1 screenshot): **0/10**; 13.1s median, \$0.0020/page.
- Security fixes in `app/main.py` (`tests/test_app.py`): single-run HTTP 409 guard and SSRF/private-IP/localhost/`.local`/`file://` rejection with DNS resolution. `pytest -q`: **45 passed**.

## Phase 6: Carbon tickets & projector-ready one-page app (done, Antigravity, ~14:15)

- `blindspot/gemini.py`: added `write_ticket(finding, url, crop_png, crop_rel_path)` using `gemini-4-carbon` to generate Markdown tickets with title, WCAG criterion & level, severity, steps to reproduce, patient experience, evidence crop path, and a CSS/HTML fix snippet.
- `blindspot/tickets.py`: `save_evidence_crop` saves `runs/<id>/tickets/<n>_evidence.png` (3 px red box around the element rect); `generate_tickets` writes `runs/<id>/tickets/<n>.md` in parallel (Carbon for top confirmed findings with deterministic Markdown fallback) and streams `ticket` SSE events.
- `blindspot/runner.py`: wired `generate_tickets` into `run_audit` (`write_tickets=True` by default, `False` in `eval/harness.py` batch loops).
- `app/main.py`: `/api/vetted` orders the 3 stable demo pages (`nyulangone.org/doctors`, `va.gov/find-locations/`, `medlineplus.gov/`) first, then the rest of `eval/pages_ok.txt`; added `GET /api/proof` returning `eval/results/results.md` + held-out manifest SHA-256 (or `"Results after the held-out run."` until Phase 8).
- `app/static/index.html`: projector-ready plain HTML + vanilla JS app with URL input, vetted dropdown, Break-it buttons (5 bugs + Random), 3 big-number KPI panels, live streaming viewport frame, zoomed red-box finding cards with "View Ticket" modal (rendered Markdown + Copy + raw `.md` link), side-by-side Blindspot vs axe-core comparison, and Proof tab.
- Verified live in browser against `http://127.0.0.1:8000/` (`medlineplus.gov` + `hide_focus`): completed in **50.87s**, **4 confirmed** (`Missing keyboard focus indicator on "What's New" header navigation link` written by Carbon with red-box crop + CSS fix), **2 axe violations** with explicit `"axe-core MISSED injected bug: hide_focus"` callout, Proof tab shows `"Results after the held-out run."`, `/submit` HTTP 200.
- Tests: `tests/test_tickets.py` added; `pytest -q`: **49 passed**.

## 2:30 Gate: Managed Agent replay (GO — 5/5 passed, Antigravity, ~14:36)

- `blindspot/replay.py`: self-contained headless Chromium replay script (zero repo imports, stdlib + Playwright only; uses in-browser canvas pixel diff so the sandbox only installs `playwright` + `chromium`). Verified locally on 3 confirmed findings (`hidden_focus.html` `focus_not_visible`, `trap.html` `keyboard_trap`, `covered.html` `focus_obscured` — all 3 `reproduced: true`).
- `blindspot/managed_agent.py`: sends `replay.py` + manifest to Google's Managed Agent sandbox (`antigravity-preview-05-2026`). **5/5 consecutive passes** on `https://medlineplus.gov/` (`hide_focus`, step 9, `changed_px=0 changed_elsewhere=0`): Attempt 1 `118.1s`, Attempt 2 `108.2s`, Attempt 3 `100.2s`, Attempt 4 `104.8s`, Attempt 5 `82.3s`.
- Wired in via `start_background_replays` in `blindspot/runner.py` (`run_replay=req.use_gemini` in `app/main.py`): spawns a daemon thread **after** `done` is emitted so it adds 0 ms to the live demo, updates `runs/<id>/findings.json` and `replays.json`, and `app/static/index.html` polls `/api/run/{run_id}` to display **`Replayed ✓`** badges on confirmed cards.

## Freeze & Held-out Manifest (done, Antigravity, ~14:55)

- `blindspot/config.py` is **FROZEN** — do not change any thresholds from now on.
- `eval/heldout_manifest.json` built from `eval/submissions.jsonl` (16 stranger URLs: 14 loadable, 2 blocked honestly in preflight — `carbonhealth.com` and `ticketmaster.com`, bot check challenge widget) via `python eval/harness.py --build-heldout-manifest --headed`.
- **Held-out manifest SHA-256:** `816e4bb137338731ce06adaf5d2c76a90c9f2ed9c985b7907332226e606f2492`

## Phase 8: Held-out Evaluation Run (done, Antigravity, ~15:24)

Ran `python eval/harness.py --set heldout --set govuk --set w3c_clean --out-prefix results` once with frozen `blindspot/config.py` and sealed `eval/heldout_manifest.json` (`SHA-256: 816e4bb137338731ce06adaf5d2c76a90c9f2ed9c985b7907332226e606f2492`). Saved `eval/results/results.json` and `eval/results/results.md` (live on the app's Proof tab).

- **`blindspot`:** **12/13** held-out injected bugs caught (`3/3 hide_focus`, `2/3 keyboard_trap`, `1/1 covering_banner`, `3/3 positive_tabindex`, `3/3 label_mismatch`), **0 false flags** across 4 W3C BAD "after" clean pages, **8** keyboard/focus findings on GOV.UK, 32.6s median, 73.8 Gemini calls/page, \$0.0362/page.
- **`code_only`:** **10/13** held-out caught, **0** W3C clean false flags, **1** on GOV.UK, 27.7s median (Blindspot beat `code_only` by +2 held-out catches and +7 GOV.UK catches with 0 false flags).
- **`axe`:** **5/12** held-out caught (`0/7` on runtime focus/trap/banner bugs), **10** violations on W3C clean pages, 6.2s median.
- **`single_gemini` (`gemini-4-argon`):** **0/13** held-out caught, **0** W3C clean false flags, 12.1s median, \$0.0022/page.
- Dropped/blocked pages reported separately (not counted as caught or missed): `carbonhealth.com` and `ticketmaster.com` (manifest preflight bot check), `headway.co` (HTTP 403), `asktia.com` (axe-only load race: no visible tabbable elements on load).

## Phase 9 (README only — HAR snapshots skipped, done, Antigravity, ~15:38)

- Finalized `README.md` with plain-language overview, HHS Section 504 May 11, 2027 deadline (15+ employees, Federal Register May 11, 2026), all model roles + 5/5 Managed Agent replay + 0.80 decision rule, held-out results table (`SHA-256: 816e4bb1...`, Blindspot 12/13 vs code_only 10/13, axe 5/12, single_gemini 0/13; 0 W3C clean false flags), dev-set table labelled as tuning data, honest limits + 4 dropped held-out pages + `failure_log.md` highlights, run instructions, and unmistakable Built-before vs. Built-at-event disclosure.
- Confirmed `.env` is not tracked in git.

## Next

Phase 10 (submit by 4:50 PM): rehearse the 3-minute live demo on `nyulangone.org/doctors`, `va.gov/find-locations/`, or `medlineplus.gov/` (restart `uvicorn` before demoing if you want the background `Replayed ✓` badge live), record the 1-minute submission video, confirm repo is public, and submit by 4:50 PM.
