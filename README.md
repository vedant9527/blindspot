# Blindspot

An AI agent that uses a website the way a keyboard or screen-reader user does, and proves where that user gets stuck. Built at the Gemini 4 NYC Hackathon (Cerebral Valley x Google DeepMind), Nov 21 2026, for Problem Statement One, "5 Sigma".

**Why healthcare:** HHS's Section 504 rule requires healthcare organizations that receive federal funding, and the vendors that build their web content and apps, to meet WCAG 2.1 Level AA. The deadline is May 11, 2027 for organizations with 15 or more employees and May 10, 2028 for smaller ones. Code scanners like axe-core miss failures that only show up on screen, such as an invisible focus outline or a banner covering the focused button. Blindspot watches the screen.

## How it works (target design)

1. Preflight loads the page, handles cookie banners, and detects bot walls and logins honestly. It never bypasses bot protection.
2. A visible Chrome window presses Tab like a keyboard user and records each step.
3. Code checks prove what they can (keyboard traps, covered focus, missing focus indicator, out-of-order focus, label mismatch).
4. Gemini 4 Hydrogen reads each step; the Gemini Decisions API scores WCAG yes/no questions per frame; Gemini 4 Argon judges hard cases.
5. Only code-backed findings are confirmed; everything else is "needs a human".
6. Gemini 4 Carbon writes tickets with evidence; a Managed Agent replays findings (stretch goal).
7. axe-core runs on the same page as the baseline, shown side by side.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium        # optional: Blindspot prefers your installed Chrome
cp .env.example .env               # then add GEMINI_API_KEY
uvicorn app.main:app --reload      # http://localhost:8000 and /submit
```

## Scripts

| Command | What it does | Needs API key |
| --- | --- | --- |
| `python scripts/check_pages.py` | Loads each page in `eval/pages_vetted.txt` three times; writes `eval/pages_ok.txt` | No |
| `python scripts/spike_runner.py --url URL` | Tabs through a page and prints the focused element, role and accessible name | No |
| `python -m blindspot.runner --url URL` | Preflight, full keyboard run and code checks; saves evidence to `runs/<id>/` | No |
| `python -m blindspot.runner --url URL --score` | Full run plus Hydrogen step reader, Decisions API scorer and `decide.py` | Yes |
| `python scripts/spike_models.py` | Lists the Gemini 4 and decision models your key can use | Yes |
| `python scripts/spike_decisions.py --url URL` | One Decisions API call on a screenshot; saves the raw response | Yes |
| `python scripts/spike_agent.py` | A Managed Agent runs one command in Google's sandbox | Yes |
| `pytest -q` | Tests | No |

## Results

Filled in after the held-out run (see `eval/results/results.md`).

## Built before the event

- Planning documents only: `AGENTS.md`, `CLAUDE.md`, `PROMPTS.md`, `docs/SPEC.md`, `docs/PLAN.md`. No code.

## Built at the event

- Phase 0: FastAPI app with the URL submission form (`/submit`), repo layout, config, axe-core vendored from npm (`vendor/axe.min.js`, MPL-2.0, license in `vendor/AXE-LICENSE`), tests.
- Phase 1: browser helpers (focused element, computed accessible name and role via the Chrome DevTools Protocol), preflight with honest block detection and cookie-banner handling, page check script, and spike scripts for the runner, models, Decisions API and Managed Agents.
- Page check run: 18 of 20 candidate healthcare pages load cleanly three times in a visible browser (`eval/pages_ok.txt`); two returned HTTP 403 and were dropped, with no bot-protection workarounds.
- QR code for the stranger URL form (`eval/submit_qr.png`).
- API checks: all four Gemini models confirmed; one Decisions API call on a real page (`docs/decisions_response_example.json`, cold call ~3 s, warm calls ~0.4 s); Managed Agent hello-world ran in Google's sandbox in 16 s.
- Phase 2: keyboard runner (screenshots, focused and unfocused crops, accessible names, coverage sampling, screen recording), code checks for keyboard traps, invisible focus, covered focus, positive tabindex and label-in-name mismatch, seven fixture pages (including late-popup dismissal) with tests, and vetted healthcare page expansion (37 of 40 public healthcare pages passing 3/3 loads in `eval/pages_ok.txt`). First real finding: on healthcare.gov, a sign-up popup hides the footer links a keyboard user is Tabbing through.
- Phase 3: Gemini 4 Hydrogen step reader (`read_step`), Gemini Decisions API per-step WCAG scorer (`score_step` with outer red-box crops, preflight warm-up call, token/usage logging, and thread-pool concurrency alongside the Tab loop), honest confirmation rule (`decide.py`: code-proven or code-suspect + high-confidence scorer agreement), and FastAPI run + SSE streaming endpoints (`POST /api/run`, `GET /api/run/{id}/events`).
- Phase 4: seeded five-bug injector (`blindspot/injector.py` with manifest + SHA-256 helper and tests on `fixtures/clean.html`), axe-core baseline (`blindspot/axe_runner.py` with `label-content-name-mismatch` enabled and `axe` SSE event), verified 5/5 injected bugs confirmed on `medlineplus.gov` vs 2/5 caught by axe-core (`positive_tabindex` and `label_mismatch`), plus SSRF and single-run concurrency hardening in `app/main.py`.
- Phase 5 (pre-freeze): Gemini 4 Argon single-screenshot baseline (`baseline_single_call`), four-system evaluation harness (`eval/harness.py`: `axe`, `single_gemini`, `code_only`, `blindspot`), Shadow DOM focus piercing and per-pixel ring contrast / disappearing-border fixes from dev-set inspection (`failure_log.md`). On the 10-case dev set: Blindspot **10/10**, code-only **10/10**, axe-core **4/10**, single-call Gemini **0/10**.
- Phase 6: Gemini 4 Carbon ticket writer (`blindspot/tickets.py`, `write_ticket` in `blindspot/gemini.py`) saving red-box evidence crops (`tickets/<n>_evidence.png`) and Markdown tickets (`tickets/<n>.md`) streamed over SSE, plus the projector-ready one-page app (`app/static/index.html`) with URL input, vetted dropdown (3 stable demo pages first), Break-it buttons, live Tab frame, zoomed finding cards, Carbon ticket modal, side-by-side axe-core comparison, and Proof tab (`/api/proof`).
- 2:30 Gate (Managed Agent replay): standalone `blindspot/replay.py` (zero repo imports) + `blindspot/managed_agent.py` verified **5/5 consecutive passes** in Google's remote Managed Agent sandbox (`antigravity-preview-05-2026`, 82–118s each), wired to run in the background after `done` so confirmed finding cards flip to **`Replayed ✓`** without slowing the live demo.

## License

MIT. axe-core is MPL-2.0.
