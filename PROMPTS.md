# Prompts to paste, in order (final)

Open your coding agent inside `~/blindspot`. Claude Code reads `CLAUDE.md`, which points to `AGENTS.md`; Google Antigravity reads `AGENTS.md` directly. No other files need uploading. Each prompt ends with a commit.

Order: Prompt A (Claude Code, now). Prompt B (Claude Code, once you have any Gemini API key). Handoff prompt (Claude Code). First Antigravity prompt. Then Prompts 2 to 9 in Antigravity. Prompts 0 and 1 from earlier versions are replaced by A and B.

---

## Prompt A. Take over, push, check pages, start the app (Claude Code, now)

Read AGENTS.md, HANDOFF.md, docs/SPEC.md and docs/PLAN.md. The hackathon has started, so everything built now goes under "Built at the event" in the README; only the planning docs are "Built before the event".

1. Check the state. If app/main.py and blindspot/browser.py exist, Phase 0 and the Phase 1 code are already built: activate .venv (create it if missing), `pip install -r requirements.txt`, run `pytest -q`, and fix anything that fails. If they don't exist, build Phase 0 from docs/PLAN.md first.
2. Git: initialise the repo if needed, make sure `.env` is not tracked, commit everything, create a public GitHub repo named `blindspot` under my account (`gh repo create blindspot --public --source=. --push`, or push to the existing remote if one is set), and tell me the repo URL.
3. Run `python scripts/check_pages.py` (headed Chrome). Show me a table of which pages passed and why the others were blocked. Keep `eval/pages_ok.txt`. Do not add any bot-protection workarounds; blocked pages simply drop out.
4. Run `python scripts/spike_runner.py --url <the first page in eval/pages_ok.txt> --tabs 10` and show me the step output.
5. Add `qrcode[pil]` to requirements.txt and install it. Start the app in the background on port 8000 bound to 0.0.0.0 (`uvicorn app.main:app --host 0.0.0.0 --port 8000`). Find my laptop's local IP (`ipconfig getifaddr en0`), and save a QR code PNG for `http://<ip>:8000/submit` to `eval/submit_qr.png`. Print the URL so I can post it in Discord, and check that `/api/health` responds.
6. If `.env` has a GEMINI_API_KEY, do Prompt B now. If not, stop and tell me to add one.
7. Update HANDOFF.md (what's done, what's verified, what's next) and the README's "Built at the event" list. Commit and push.

---

## Prompt B. Run the API checks (Claude Code, once a Gemini API key is in .env)

A free Google AI Studio key works for this; the event credits key can replace it later. Run these and show me the output of each:

1. `python scripts/spike_models.py`: confirm `gemini-4-hydrogen`, `gemini-4-argon`, `gemini-4-carbon` and `gemini-decision-1` exist for this key. If a name differs, update `blindspot/config.py` and tell me.
2. `python scripts/spike_decisions.py --url <the first page in eval/pages_ok.txt>`: it must save `docs/decisions_response_example.json`. Check the response matches the shape in HANDOFF.md (answers[id].noul, .confidence, .choice, .probabilities); note any difference in HANDOFF.md.
3. `python scripts/spike_agent.py`: the Managed Agent should print "blindspot ok". It can take a minute or more. If it fails, report the error and continue; the replay is a gated stretch goal.

Then update HANDOFF.md with the results, commit and push.

---

## Handoff prompt (last thing you paste in Claude Code)

We're switching coding agents now; Google Antigravity will continue from here with no access to this conversation. Update HANDOFF.md with: what is done and verified working, exact commands to set up and run everything, which keys are needed in .env, results of Prompt B (or "not done yet"), any API quirks found, open issues, and the next prompt to run from PROMPTS.md. Update the README's "Built before the event" and "Built at the event" lists. Make sure .env is not tracked. Stop the background app. Commit and push.

---

## First prompt in Google Antigravity

Open `~/blindspot` in Antigravity, choose Gemini 4 Neon as the agent model (switch to Carbon for hard debugging), put the event API key in `.env`, then paste:

Read AGENTS.md, @docs/SPEC.md, @docs/PLAN.md, @HANDOFF.md and the last 10 git commits. Tell me in five lines what is done, what is next, and anything that looks broken. Run `pytest -q`. If Prompt B in @PROMPTS.md is not done, do it now with the key in .env. Otherwise continue with Prompt 2. Follow every rule in AGENTS.md, and update HANDOFF.md at the end of each phase.

---

## Prompt 2. Runner, fixtures and code checks

Do Phase 2 exactly per SPEC sections 2, 3 and 4. Reuse blindspot/browser.py and blindspot/preflight.py, which already exist. Start with the six fixtures and tests, then runner.py and checks.py until pytest passes. Then run the runner on two pages from eval/pages_ok.txt and show me the step records and any proven checks. Keep the 40-Tab, 60-second and 15-second caps. Commit after the tests pass and again after the real-page run.

---

## Prompt 3. Gemini reading, scoring and the decision rule

Do Phase 3 per SPEC sections 5 and 6. Write the Decisions API parser from docs/decisions_response_example.json and the shape in HANDOFF.md. Put all thresholds in blindspot/config.py. Wire scoring and decisions into the run and stream step and finding events over SSE. Run every fixture and clean.html and show me what was confirmed, needs_human and dropped. Commit.

---

## Prompt 4. Injector and axe-core

Do Phase 4 per SPEC sections 7 and 8. Add tests for the injector on clean.html. Then inject each of the five bugs into one page from eval/pages_ok.txt and show me that each produces a confirmed finding, plus what axe-core reported for the same page. Commit.

---

## Prompt 5. Gate check, baselines and freeze

First run the full pipeline on three pages from eval/pages_ok.txt and tell me plainly whether the 1:30 gate passes. Then do Phase 5: the single-call baseline and code_only system in eval/harness.py, a dev-set run, and a failure_log.md line for every miss or false flag with the fix. At 2:00 I will say "freeze": then build eval/heldout_manifest.json from eval/submissions.jsonl, print its SHA-256, and commit. Do not change config.py after the freeze.

---

## Prompt 6. Tickets and the app

Do Phase 6 per SPEC sections 9 and 12. Carbon tickets with red-box crops, and the one-page app: URL box, vetted dropdown (from eval/pages_ok.txt), Break it buttons (five bugs plus Random), live frame, findings cards, axe column side by side, Proof tab rendering eval/results/results.md. Make it readable on a projector: large fonts, zoomed crops, one big number per panel. Run one full demo in the browser and tell me what's on screen at the end. Commit.

---

## Prompt 7. Managed Agent replay (go or no-go at 2:30)

Do the 2:30 gate in PLAN.md. Write replay.py with no imports from the repo, test it locally on three confirmed findings, then run it through managed_agent.py five times in a row. Report pass or fail for each attempt. If all five pass, wire it in so cards show "replayed". If not, tell me, mark it "planned" in the README, and stop.

---

## Prompt 8. Held-out run

Do Phase 8. Run the harness once on heldout, govuk and w3c_clean for all four systems. Show me results.md. Do not re-run or tune after seeing the numbers; if something crashed, fix the crash only and log it in failure_log.md. Commit the results.

---

## Prompt 9. Snapshots and final README

Do Phase 9's snapshot mode (record HAR for the pages in eval/pages_ok.txt, replay with route_from_har behind a "Snapshot" toggle in the app). Then write the final README: what Blindspot does, how to run it, the results table, known failures from failure_log.md, the healthcare context (HHS Section 504, WCAG 2.1 AA, May 2027), and the "Built before the event" and "Built at the event" lists. Make sure .env is not committed. Commit and push.

---

## If something breaks under time pressure

Paste: "We're over the time box for this step. Propose the simplest version that keeps the demo working, do it, and commit. Log what we cut in failure_log.md."
