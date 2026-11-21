# Blindspot (shared rules for Claude Code and Google Antigravity)

An AI agent that uses a website the way a keyboard or screen-reader user does, and proves where that user gets stuck. Built solo at the Gemini 4 NYC Hackathon (Cerebral Valley x Google DeepMind), Sat Nov 21 2026, for Problem Statement One, "5 Sigma".

Pitch: "Every hospital, clinic and health app vendor that takes federal money must make its patient portals accessible by May 2027 (HHS Section 504, WCAG 2.1 AA). Scanners like axe-core miss the failures that lock patients out. Blindspot uses the site like those patients do, and proves what it finds."

Read `docs/SPEC.md` for the technical spec and `docs/PLAN.md` for the build phases before starting any task.

## Hackathon rules that constrain the code

- Hacking runs 10:30 AM to 5:00 PM. Submit by 4:50 PM.
- The repo must be public. Only work done during the event may be demoed. Keep the README sections "Built before the event" and "Built at the event" accurate after every phase.
- At least two Gemini 4 models, each with a clear job, plus the Gemini Decisions API. Media must be central (here: the screen recording of a keyboard session).
- Not allowed: scripted demos, evaluations made only of examples we wrote. Banned: image analyzers, dashboard-as-main-feature, Streamlit, basic RAG, chatbots. The product output is the ticket with its evidence, not a findings dashboard.
- Never use data, code or assets we don't have rights to. No employer data.

## Stack

- Python 3.12, FastAPI, uvicorn. Frontend is one plain HTML page with vanilla JS. No Streamlit, no React build step.
- Playwright for Python with Chrome (`channel="chrome"`), headed (visible) for the live demo, headless only for eval batches and replay.
- `google-genai` SDK for Gemini models and the Decisions API.
- axe-core injected as `vendor/axe.min.js` from the npm package (`npm pack axe-core`), run with `page.evaluate("axe.run()")`.
- Storage: JSON files under `runs/` and `eval/results/`. No database.
- Pillow and numpy for image crops and pixel checks.

## Models and their one job each

| Component | Model ID (verify in AI Studio) | Job |
| --- | --- | --- |
| Reader | `gemini-4-hydrogen` | Reads each step's screenshot crop: visible label text, whether an indicator shows |
| Scorer | `gemini-decision-1` via the Decisions API | One call per step with the WCAG yes/no questions, each with a 0-1 confidence |
| Hard calls (optional) | `gemini-4-argon` | Judges cases where code and the scorer disagree; also runs the single-call baseline |
| Ticket writer | `gemini-4-carbon` | Writes each ticket: WCAG criterion, steps, evidence, suggested fix |
| Replay (gated) | Gemini API Managed Agents | Re-runs `replay.py` for each confirmed finding in Google's sandbox |

Hydrogen plus Carbon already satisfy the two-model rule, so Argon can be cut without breaking the rules.

## Non-negotiable behaviors

1. Never bypass bot protection. No stealth plugins, CAPTCHA solvers, rotating proxies or fake user agents. Detect blocks in preflight and report them honestly.
2. A finding is "confirmed" only if code proves it, or the Decisions API is above threshold AND code agrees. Everything else is "needs_human" or dropped. Never report a guessed pass.
3. Every run has hard caps: 40 Tab presses, 60 seconds, 15-second page load timeout. Stream progress so the screen is never idle.
4. Cookie banners: try reject or close buttons first, accept only as a last resort, and log which one was clicked. A banner covering the focused element is a finding (WCAG 2.4.11), not something to hide.
5. Public pages only. Never log in, never submit forms, never enter personal data.
6. Secrets live in `.env` (GEMINI_API_KEY, GEMINI_API_KEY_BACKUP). Never commit `.env`. Commit `.env.example`.

## API notes (check docs before coding against them)

- Decisions API: `client = genai.Client(http_options={"api_version": "v1beta"})`, then `client.decisions.create(model="gemini-decision-1", input=[...], questions={...})`. Question types: `noul` (yes/no), `choice` (2-255 options, `criteria` maps option name to description), `score` (ordered rubric, `criteria` is a list of level descriptions). Up to 1,000 questions and 256K input tokens per call; about 150-250 ms. Response field names are not in the launch post: print the first raw response, then write the parser from what you see. Docs: https://blog.google/innovation-and-ai/technology/developers-tools/gemini-decisions-api/ and https://codelabs.developers.google.com/getting-started-with-gemini-decisions-api
- Managed Agents: Interactions API, agent `antigravity-preview-05-2026`, `"environment": "remote"`, header `Api-Revision: 2026-05-20`. One interaction can use 100k to 3M tokens and is slow, so it never sits on the live demo path. Docs: https://ai.google.dev/gemini-api/docs/agents and https://ai.google.dev/gemini-api/docs/managed-agents-quickstart
- Wrap every Gemini call in one module (`blindspot/gemini.py`) with retries, an 8-second timeout, a backup key and a log of model ID, latency and token counts.

## Repo layout

```
app/main.py                FastAPI: run API, SSE stream, submit form, static files
app/static/index.html      The one-page app
app/static/submit.html     QR form for stranger URLs
blindspot/browser.py       Browser launch and focused-element facts (CDP accessible name)
blindspot/runner.py        Keyboard runner: Tab loop, screenshots, focus data
blindspot/preflight.py     Load, banner handling, block detection
blindspot/checks.py        Code checks: trap, obscured, focus visible, order, label in name
blindspot/gemini.py        All model calls (Hydrogen, Decisions, Argon, Carbon)
blindspot/decide.py        Decision rule: confirmed / needs_human / dropped
blindspot/injector.py      Five injected bugs with a seeded manifest
blindspot/axe_runner.py    axe-core baseline on the same page
blindspot/tickets.py       Carbon tickets and evidence crops with a red box
blindspot/replay.py        Self-contained headless replay script (also used by the Managed Agent)
blindspot/managed_agent.py Sends replay jobs to a Managed Agent
eval/harness.py            Runs all systems over test sets, writes results
eval/pages_vetted.txt      15-20 public healthcare pages that load cleanly
eval/submissions.jsonl     Stranger URLs from the QR form
fixtures/                  Local test pages with known bugs, for pytest
tests/                     pytest for checks and injector against fixtures
scripts/                   check_pages.py and Phase 1 spike scripts
HANDOFF.md                 Where the build stands; read after AGENTS.md
failure_log.md             One line per failure and fix, committed as we go
```

## Working style

- Small steps. After each working step: run tests, commit with a clear message, and update the README "Built at the event" list.
- If a step runs 20 minutes over its time box in `docs/PLAN.md`, stop and propose the simpler version.
- Prefer plain, readable code over abstractions. Type hints, docstrings on public functions.
- When a check fails on a real page, add one line to `failure_log.md`: page, what went wrong, the change, the re-run result.
- Before the 2:00 PM freeze, thresholds live in `blindspot/config.py`. After the freeze, do not change them.
- At the end of every phase, update `HANDOFF.md`: what is done and working, how to run it, open issues, decisions made, and the next phase. Another coding agent (Claude Code or Google Antigravity) may pick up from this file with no other context.
- Only one coding agent works in the repo at a time. Commit and push before switching tools.
