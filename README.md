# Blindspot

Blindspot presses `Tab` through real public healthcare websites the way a keyboard or screen-reader patient does, proves where they get stuck, and writes an evidence ticket with a concrete fix for each confirmed problem.

Built solo at the **Gemini 4 NYC Hackathon** (Cerebral Valley × Google DeepMind), Sat Nov 21, 2026, for Problem Statement One ("5 Sigma").

---

## Why healthcare

Under **HHS Section 504**, hospitals, clinics, insurers, and health-app vendors that receive federal funding must make their web content accessible to **WCAG 2.1 Level AA**. HHS extended the compliance deadline to **May 11, 2027** for organizations with 15 or more employees (*Federal Register*, May 11, 2026).

Static DOM scanners like `axe-core` miss runtime failures that only appear when someone actually navigates the page by keyboard — an invisible focus ring, a sticky banner covering the focused button, or a widget that traps keyboard focus. Blindspot uses the site like a patient does and proves what it finds.

---

## How it works & model roles

Every run loads a public page (up to 40 `Tab` presses, 60-second hard cap, 15-second load timeout), captures full screenshots, focused/unfocused crops, hit-test coverage, and Chrome DevTools Protocol (CDP) computed accessible names, then combines deterministic code checks with Gemini 4 models:

| Component | Model / Tool | Single Job |
| --- | --- | --- |
| **Code checks** | `blindspot/checks.py` | Proves what code can prove: keyboard traps (2.1.2), invisible/off-screen focus (2.4.7), fully obscured focus behind fixed/sticky layers (2.4.11), positive `tabindex` (2.4.3), and visible-label vs. accessible-name mismatch (2.5.3); flags low-contrast rings (1.4.11) and upward focus jumps as suspects. |
| **Frame reader** | `gemini-4-hydrogen` | Reads each step's unannotated crop + full viewport screenshot and returns `{visible_label, indicator_visible, notes}`. |
| **WCAG scorer** | `gemini-decision-1` (Decisions API) | Runs one warm-up `page_state` check in preflight, then scores per-step WCAG yes/no (`noul`) questions with 0–1 confidence in a thread pool alongside the `Tab` loop. |
| **Ticket writer** | `gemini-4-carbon` | Writes a Markdown bug ticket per confirmed finding (WCAG criterion, severity, reproduction steps, patient impact, red-box evidence crop, and CSS/HTML fix). |
| **Single-call baseline** | `gemini-4-argon` | Runs the single full-page screenshot baseline in `eval/harness.py`. |
| **Sandbox replay** | Gemini Managed Agent (`antigravity-preview-05-2026`) | Re-runs standalone `blindspot/replay.py` in Google's remote sandbox to independently verify confirmed findings (**5/5 consecutive passes** at the 2:30 gate). Runs in the background after `done` so it never slows the live demo. |
| **Static baseline** | `axe-core` 4.14.1 (`vendor/axe.min.js`) | Runs on the exact same loaded page (with `label-content-name-mismatch` enabled) for a fair side-by-side comparison. |

### Honest decision rule (`blindspot/decide.py`)
- **Confirmed:** Code proves the failure (`proven == True`), **or** code flags a suspect on that step **and** the Decisions API failing probability is at least **`0.80`** (`CONFIRM_P`).
- **Needs a human:** Decisions API probability is between `0.40` and `0.80`, or the scorer flags a failure (`>= 0.80`) that code cannot support, or code flags a suspect the scorer did not confirm.
- **Dropped:** Below `0.40` with no code flag, or if sandbox replay fails to reproduce. Blindspot never reports a guessed pass.

---

## Results

### Held-out evaluation (frozen thresholds, unseen stranger-submitted sites)

Collected **16 stranger-submitted websites** via `/submit` (`eval/submissions.jsonl`), sealed the seeded injection manifest in `eval/heldout_manifest.json` (**SHA-256: `816e4bb137338731ce06adaf5d2c76a90c9f2ed9c985b7907332226e606f2492`**) and committed it at **2:57 PM** before running the harness once across `heldout`, `govuk`, and `w3c_clean` (`eval/results/results.md`, `eval/results/results.json`).

| System | Held-out Injected Caught | `hide_focus` | `keyboard_trap` | `covering_banner` | `positive_tabindex` | `label_mismatch` | W3C Clean (4 pages) | Median s/page | Gemini Calls/page | Est. Cost/page |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `axe` | **5/12** | 0/3 | 0/3 | 0/1 | 2/2 | 3/3 | 10* | 6.2s | 0.0 | \$0.0000 |
| `single_gemini` | **0/13** | 0/3 | 0/3 | 0/1 | 0/3 | 0/3 | 0 | 12.1s | 1.0 | \$0.0022 |
| `code_only` | **10/13** | 2/3 | 2/3 | 1/1 | 3/3 | 2/3 | 0 | 27.7s | 0.0 | \$0.0000 |
| **`blindspot`** | **12/13** | **3/3** | **2/3** | **1/1** | **3/3** | **3/3** | **0** | 32.6s | 73.8 | \$0.0362 |

*\*Note on W3C BAD "after" clean pages (`home`, `news`, `tickets`, `survey`):* **axe-core reported 10 issues on the W3C pages meant to be clean (other rule types); Blindspot reported 0.**

- **GOV.UK Accessibility Tool Audit page (raw counts, not scored accuracy):** `axe`: 22, `single_gemini`: 2, `code_only`: 1, `blindspot`: 8.
- **Why Gemini matters on top of code:** On held-out unseen sites, `blindspot` caught **12/13** vs. `code_only` **10/13** (+2 unseen catches), while keeping **0** false flags on W3C clean pages.

### Dev-set results (tuning data only — used before the freeze)

10 seeded cases across 5 vetted public healthcare pages (`eval/results/dev_results.md`, strictly separate from `eval/submissions.jsonl`):

| System | Dev Injected Caught | `hide_focus` | `keyboard_trap` | `covering_banner` | `positive_tabindex` | `label_mismatch` | Median s/page | Gemini Calls/page | Est. Cost/page |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `axe` | **4/10** | 0/2 | 0/2 | 0/2 | 2/2 | 2/2 | 8.1s | 0.0 | \$0.0000 |
| `single_gemini` | **0/10** | 0/2 | 0/2 | 0/2 | 0/2 | 0/2 | 13.1s | 1.0 | \$0.0020 |
| `code_only` | **10/10** | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 29.5s | 0.0 | \$0.0000 |
| **`blindspot`** | **10/10** | **2/2** | **2/2** | **2/2** | **2/2** | **2/2** | 37.0s | 72.4 | \$0.0340 |

---

## Honest limits & failure log

### Scope & limits
- **Coverage:** Tests **5 keyboard and focus failure categories** (plus WCAG 1.4.11 non-text contrast suspects), not full WCAG 2.1 AA. Blindspot does **not** certify legal compliance.
- **Public pages only:** Never logs in, submits forms, enters personal data, or audits authenticated patient portals.
- **Honest block reporting (no bypasses):** Sites with bot protection or challenge widgets are detected in preflight, reported as blocked, and dropped without workarounds. On the held-out set, **4 pages** dropped out (never counted as caught or missed):
  - `https://carbonhealth.com/` — `bot check (challenge widget)` (manifest preflight)
  - `https://www.ticketmaster.com/` — `bot check (challenge widget)` (manifest preflight)
  - `https://headway.co/` — `HTTP 403` (all 4 systems)
  - `https://asktia.com/` — `RuntimeError: No visible tabbable elements found on load` (`axe` run only)
- **Injector reachability:** Seeded bugs target elements in the **first screen (first 15 tabbable elements)** so the 40-Tab run can reach them (with room left for trap detection).
- **GOV.UK counts:** The GOV.UK numbers above are raw finding counts on the audit test page, not scored precision/recall.

### Key failures caught and fixed during development (`failure_log.md`)
- **Late sign-up popups (`medicare.gov`, `healthcare.gov`):** Random Qualtrics popups appeared after load and trapped/obscured focus → added mid-run overlay dismissal (`dismiss_popup` in reject → close → accept order, logged in `run["popups"]`) and cycle detection after loops of 3+ distinct elements.
- **Shadow DOM focus dilution (`va.gov/find-locations/`):** `document.activeElement` returned the `1280×80` Shadow DOM host (`<va-header-navigation>`), diluting `mean_diff` to `0.41–1.22` and causing 3 false `focus_not_visible` flags → pierced open `shadowRoot.activeElement` in `browser.py` and `runner.py` (0 false flags on re-run).
- **Large-box & mixed text+ring contrast (`medlineplus.gov`):** Large logo interiors diluted whole-crop `mean_diff`, and text color swaps mixed with black dotted outlines diluted contrast to `2.19:1` → switched `pixel_stats` in `checks.py` to per-changed-pixel WCAG contrast (`strong_ring_px`), eliminating false flags while still catching genuine `<3:1` rings (e.g., `cms.gov`'s `2.87:1` tan ring).
- **Disappearing-border focus loss (`nyulangone.org/doctors`):** Unfocused pill border on a child element vanished into white on `:focus` (`changed_px=404`, scorer `fail_p=0.84`) → added `border_vanished` suspect detection in `checks.py` and locked descendant borders in `injector.py`.
- **Gemini API 10s deadline floor:** `gemini-4-argon` rejected an 8-second `HttpOptions` deadline with HTTP `400` (`Minimum allowed deadline is 10s`) → set `GEMINI_TIMEOUT_S = 10.0` and `GEMINI_GEN_TIMEOUT_S = 20.0`.
- **Headless 403s & disk space:** 6 of 18 vetted pages and `telehealth.hhs.gov` returned blocks in `--headless` mode (passing headed Chrome) → no bypasses added; swapped `telehealth.hhs.gov` to `kp.org` in dev set, and disabled video + cleaned per-step PNGs after each batch eval case to protect disk space.

---

## How to run it

### 1. Setup & environment
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium        # Blindspot prefers installed Chrome when available
playwright install ffmpeg          # optional, for .webm session recordings
cp .env.example .env               # add GEMINI_API_KEY (and optional GEMINI_API_KEY_BACKUP)
```
Keys in `.env` (never committed):
- `GEMINI_API_KEY` — required for Hydrogen, Decisions API, Argon, Carbon, and the Managed Agent.
- `GEMINI_API_KEY_BACKUP` — optional fallback key used automatically on API errors.

### 2. Run the web app (projector UI + stranger QR form)
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```
- Live audit app & Proof tab: `http://localhost:8000/`
- Stranger URL submission form: `http://localhost:8000/submit`

### 3. Run from the CLI
```bash
# Full keyboard run + Hydrogen + Decisions API + Carbon tickets + axe-core
python -m blindspot.runner --url https://medlineplus.gov/ --score

# Inject one of the five bugs with a fixed seed
python -m blindspot.runner --url https://medlineplus.gov/ --score --inject hide_focus --seed 101

# Standalone headless replay (no repo imports)
python blindspot/replay.py --url https://medlineplus.gov/ --tabs 9 --check focus_not_visible

# Evaluation harness
python eval/harness.py --set dev --out-prefix dev_results
python eval/harness.py --set heldout --set govuk --set w3c_clean --out-prefix results
```

### 4. Tests
```bash
pytest -q                          # 49 tests (fixtures, decide.py, injector, axe, tickets, app security)
```

---

## Built before the event

**Planning documents only — zero code, zero fixtures, zero test data:**
- `AGENTS.md`, `CLAUDE.md`, `PROMPTS.md`, `docs/SPEC.md`, `docs/PLAN.md`.

## Built at the event

Everything runnable in this repository was built on Saturday, Nov 21, 2026:
- **Phase 0:** Repo scaffold, `blindspot/config.py`, FastAPI app (`app/main.py`) with `/submit` QR form (`eval/submit_qr.png`), vendored `axe-core` 4.14.1 (`vendor/axe.min.js`, MPL-2.0), and initial tests.
- **Phase 1:** Browser helpers (`blindspot/browser.py` with CDP accessible name/role), honest preflight & cookie-banner handler (`blindspot/preflight.py`), vetted page checker (`scripts/check_pages.py` → 37 of 40 public healthcare pages passing 3/3 loads in `eval/pages_ok.txt`), and API spikes (`scripts/spike_models.py`, `spike_decisions.py` → `docs/decisions_response_example.json`, `spike_agent.py`).
- **Phase 2:** Keyboard runner (`blindspot/runner.py` with screenshots, crops, coverage sampling, mid-run popup dismissal, and `.webm` recording), code checks (`blindspot/checks.py`), and 7 local fixture pages (`fixtures/*.html`) with `pytest` suite.
- **Phase 3:** Gemini 4 Hydrogen step reader (`read_step`), Decisions API parser + per-step scorer (`score_step`, preflight warm-up, usage/token logging, outer red-box crops, thread-pool concurrency) in `blindspot/gemini.py`, honest decision rule (`blindspot/decide.py`), and `POST /api/run` + SSE `GET /api/run/{id}/events` streaming in `app/main.py`.
- **Phase 4:** Seeded five-bug injector (`blindspot/injector.py` with SHA-256 manifest support), `axe-core` runner (`blindspot/axe_runner.py` with `axe` SSE event), SSRF/private-IP URL validation and single-run HTTP 409 guard in `app/main.py`.
- **Phase 5:** Gemini 4 Argon single-screenshot baseline (`baseline_single_call`), four-system evaluation harness (`eval/harness.py`), 1:30 gate verification, dev-set run, and pre-freeze fixes (Shadow DOM piercing, per-pixel ring contrast, disappearing-border detection, 10s API deadline floor).
- **Phase 6:** Gemini 4 Carbon ticket writer (`blindspot/tickets.py`, `write_ticket`) saving red-box crops and Markdown tickets streamed over SSE, plus the projector-ready vanilla HTML/JS one-page app (`app/static/index.html`) with vetted dropdown, Break-it controls, live frame, zoomed finding cards, ticket modal, side-by-side axe comparison, and Proof tab (`/api/proof`).
- **2:30 Gate (Managed Agent replay):** Standalone `blindspot/replay.py` (zero repo imports) and `blindspot/managed_agent.py` verified **5/5 consecutive passes** in Google's remote sandbox and wired into background post-run verification (`Replayed ✓` card badges).
- **Freeze & Phase 8 (Held-out evaluation):** Froze `blindspot/config.py`, built & sealed `eval/heldout_manifest.json` (`SHA-256: 816e4bb137338731ce06adaf5d2c76a90c9f2ed9c985b7907332226e606f2492`) from 16 stranger-submitted URLs, and ran all four systems once across `heldout`, `govuk`, and `w3c_clean` (`eval/results/results.md`).
- **Phase 9 (Documentation):** Finalized `README.md` with full held-out & dev tables, honest limits, failure log summary, and clear built-before vs. built-at-event disclosure.

---

## License

MIT. Vendored `axe-core` (`vendor/axe.min.js`) is MPL-2.0 (`vendor/AXE-LICENSE`).
