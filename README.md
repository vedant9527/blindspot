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

## License

MIT. axe-core is MPL-2.0.
