# Blindspot build plan (solo)

Gates: the core run works end to end by 1:30 PM, thresholds freeze at 2:00 PM, the Managed Agent replay gets a go or no-go at 2:30 PM, nothing new after 3:30 PM, submit by 4:50 PM.

## Phase 0. Before 10:30 (setup only, disclosed in the README)

- [ ] Public MIT repo, README with "Built before the event" and "Built at the event" sections, `.env.example`, `.gitignore` (includes `.env`, `runs/`, `node_modules/`).
- [ ] `pip install fastapi uvicorn playwright google-genai python-dotenv pillow numpy pytest httpx`, then `playwright install chrome`.
- [ ] `vendor/axe.min.js` from the axe-core npm package.
- [ ] FastAPI app serving an empty `index.html` and a plain `submit.html` form that appends `{url, timestamp}` to `eval/submissions.jsonl`.
- [ ] `eval/pages_vetted.txt`: 15 to 20 public healthcare pages (appointment request, find a doctor, pay a bill, telehealth info, public insurer and government health pages), each loaded three times in a visible browser without a bot check or login.
- [ ] Tag `pre-event-scaffold`.

Accept: `uvicorn app.main:app` serves both pages; the submit form writes a line.

## Phase 1. 10:30 to 10:50, kill-switch tests

- [ ] `scripts/spike_decisions.py`: one Decisions API call on a screenshot with five noul questions. Print the raw response and save it to `docs/decisions_response_example.json`.
- [ ] `scripts/spike_runner.py`: headed Chrome tabs through one vetted page 10 times and prints selector, rect and accessible name per step.
- [ ] `scripts/spike_agent.py`: a Managed Agent interaction that runs `python -c "print('ok')"` and returns the output.
- [ ] Post the QR form link in Discord #general.

Accept: all three print real output. If the Decisions API spike fails, stop and fix it first; it is the riskiest dependency.

## Phase 2. 10:50 to 12:15, runner, preflight and code checks

- [ ] `fixtures/`: clean.html, trap.html, hidden_focus.html, covered.html, tabindex.html, label_mismatch.html (10 to 20 focusable elements each).
- [ ] `runner.py` and `preflight.py` per SPEC sections 2 and 3.
- [ ] `checks.py` per SPEC section 4.
- [ ] `tests/test_checks.py`: each fixture triggers exactly its check; clean.html triggers none.

Accept: `pytest` passes; a run on two vetted pages completes in under 60 s each.

## Phase 3. 12:15 to 1:00, Gemini reading, scoring and the decision rule

- [ ] `gemini.py`: `read_step`, `score_step` (parser written from the saved example response), retries, timeout, backup key, call log.
- [ ] `decide.py` with thresholds in `config.py`.
- [ ] Wire into the run; stream `step` and `finding` events over SSE.

Accept: on each fixture, the right finding is confirmed; on clean.html nothing is confirmed.

## Phase 4. 1:00 to 1:30, injector and axe-core

- [ ] `injector.py` with the five bugs and a seeded manifest; `tests/test_injector.py` on clean.html.
- [ ] `axe_runner.py` and the axe event in the stream.
- [ ] At lunch, ask five teams to submit URLs.

Accept: injecting each bug into a vetted page produces a confirmed finding for that bug.

## GATE at 1:30

The full run (preflight, run, checks, scoring, decision, axe) works on three vetted pages. If not: cut Argon and the replay now and spend the time on the core.

## Phase 5. 1:30 to 2:00, baselines, fixes, freeze

- [ ] `baseline_single_call` (Argon) and the `code_only` system in `eval/harness.py`.
- [ ] Run the dev set; for every miss or false flag, add a line to `failure_log.md`, fix, commit.
- [ ] 2:00: freeze `config.py`. Build `eval/heldout_manifest.json` from the submissions, compute and display its SHA-256, commit it.

## Phase 6. 2:00 to 2:30, tickets and the app

- [ ] `tickets.py` with Carbon and red-box crops.
- [ ] `index.html`: URL box, vetted dropdown, Break it buttons, live frame, findings cards, axe column, Proof tab.

Accept: a full demo run in the browser ends with at least one ticket and the axe comparison on screen.

## GATE at 2:30, Managed Agent replay

- [ ] `replay.py` (self-contained) works locally on three findings.
- [ ] `managed_agent.py` runs it in the sandbox five times in a row. If yes, wire it in until 3:15 and show "replayed" on cards. If no, mark it "planned" in the README and use the time for snapshots and polish.

## Phase 7. 3:15 to 3:30, only if everything above works

- [ ] Argon `judge_hard` for disagreements, or short video clips per finding.

## Phase 8. 3:30 to 4:00, held-out run

- [ ] `python eval/harness.py --set heldout --set govuk --set w3c_clean` once, for all four systems.
- [ ] Commit `results.json` and `results.md`; check the Proof tab.

## Phase 9. 4:00 to 4:30, snapshots and rehearsal

- [ ] Record HAR snapshots of the vetted pages (`record_har_path`) and add a snapshot mode that replays with `route_from_har`.
- [ ] Rehearse the 3-minute demo three times with pages and bugs picked by strangers.

## Phase 10. 4:30 to 4:50, submit

- [ ] Record the 1-minute video: keyboard run, a judge-style injected bug caught, a ticket, the results table.
- [ ] Finish the README: what it does, how to run it, results, known failures, built before vs at the event.
- [ ] Confirm the repo is public; submit by 4:50.
