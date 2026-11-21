# Blindspot technical spec

## 1. Run flow

1. `POST /api/run` with `{url, inject: null | "<bug_type>" | "random", seed}` returns a `run_id`.
2. `GET /api/run/{run_id}/events` streams Server-Sent Events: `preflight`, `step`, `finding`, `axe`, `ticket`, `done`, `error`.
3. The run: preflight, optional injection, keyboard run, code checks per step, Gemini reading and scoring per step, decision rule, tickets for confirmed findings, axe-core on the same page.
4. Everything for a run is saved to `runs/<run_id>/` (steps.json, findings.json, crops/*.png, axe.json, tickets/*.md, run.log).

## 2. Preflight (`preflight.py`, 5-second budget after load)

- `page.goto(url, timeout=15000, wait_until="domcontentloaded")`, then wait up to 2 s for network idle.
- Blocked if any of these hold:
  - HTTP status 403, 429 or 503.
  - Page text matches /just a moment|verify you are human|access denied|are you a robot|checking your browser/i.
  - An iframe from challenges.cloudflare.com, google.com/recaptcha or hcaptcha.com.
  - The URL redirected to a path containing login, signin or sso, or the page has an `input[type=password]`.
  - Fewer than 5 tabbable elements.
- One Decisions API call on the screenshot: `page_state` as a choice of normal, bot_check, login_wall, error_page, cookie_banner. Use it as a second signal, never the only one.
- Cookie banner: look for buttons matching /reject|decline|necessary only/i first, then /close|dismiss/i, then /accept|agree|allow/i. Known selectors: `#onetrust-reject-all-handler`, `#onetrust-accept-btn-handler`. Log which was clicked.
- Result: `{status: "ok" | "blocked", reason, banner_action}`. A blocked page ends the run with a clear message and a pointer to the vetted list and saved snapshots.

## 3. Keyboard runner (`runner.py`)

- Headed Chrome, viewport 1280x800, `record_video_dir` set (video is optional evidence).
- Click the page body at a neutral spot first so keyboard focus starts in the document.
- Loop up to 40 times: press Tab, wait 150 ms, then capture a step record:
  - `index`
  - `selector`: a stable CSS path built in JS (id if unique, else tag plus nth-of-type chain)
  - `tag`, `role`, `accessible_name`: use a CDP session, `Accessibility.getPartialAXTree` on the focused node; fall back to aria-label, aria-labelledby, then innerText
  - `visible_text`: the element's innerText, trimmed
  - `rect`: getBoundingClientRect in viewport coordinates
  - `scroll_y`
  - `focused_crop`: a screenshot clipped to the rect plus 12 px padding
  - `full_screenshot` (every step, saved to disk)
- Stop early if focus returns to the first element (one full cycle) or 60 s pass.
- Shift+Tab escape test for the trap check: after a suspected trap, press Shift+Tab three times and record whether focus leaves.

## 4. Code checks (`checks.py`)

Each check returns `{check, wcag, proven: bool, evidence, detail}`.

| Check | WCAG | How code proves it |
| --- | --- | --- |
| keyboard_trap | 2.1.2 (A) | Over the last 10 steps, 2 or fewer distinct selectors, while the page has 10+ tabbable elements, and Shift+Tab doesn't escape either |
| focus_not_visible | 2.4.7 (AA) | Crop the element plus padding while focused; call `el.blur()`; crop again; `el.focus()` back. Mean absolute pixel difference below `FOCUS_DIFF_MIN` (start at 3.0 on 0-255) means no visible indicator. Caveat: programmatic focus can drop :focus-visible styles, so take the focused crop from the keyboard step, not after refocusing |
| focus_obscured | 2.4.11 (AA, WCAG 2.2) | Sample the element's center and four inset corners with `document.elementFromPoint`. If every point returns an element that is not the target or its descendant, and that element or an ancestor is `position: fixed` or `sticky`, it's entirely hidden (proven). Partly hidden goes to needs_human |
| focus_order | 2.4.3 (A) | Positive `tabindex` anywhere in the DOM is proven (known failure technique F44). Separately, a jump where the next element's top is more than `ORDER_JUMP_PX` (start at 300) above the previous one, outside a new landmark, is a suspect for the scorer and Argon |
| label_in_name | 2.5.3 (A) | Normalize both strings (lowercase, strip punctuation and whitespace). If the visible text is non-empty and not contained in the accessible name, it's proven |
| indicator_contrast | 1.4.11 (AA) | Among pixels that changed between focused and unfocused crops, the contrast ratio between the focused color and the unfocused color is below 3:1. Treat as suspect only; confirm with the scorer |

## 5. Gemini calls (`gemini.py`)

- `read_step(crop, full_screenshot)`: Hydrogen returns JSON `{visible_label, indicator_visible: bool, notes}`.
- `score_step(crop, full_screenshot, context_text)`: one Decisions API call with these questions:
  - `focus_visible` (noul): "Is there a visible focus indicator on the element in the red box?"
  - `focus_covered` (noul): "Is the focused element covered by another element such as a banner or popup?"
  - `label_matches` (noul): "Does the visible label text match the announced name: '<accessible_name>'?"
  - `indicator_faint` (noul): "Is the focus indicator too faint to see easily?"
  - `order_logical` (noul, only when the order code flags a suspect): "Given the previous and current focus positions, is this a logical next step?"
- `judge_hard(case)`: Argon, only when the scorer and code disagree. Returns `{verdict: confirmed | needs_human, reason}`.
- `write_ticket(finding)`: Carbon returns Markdown with: title, WCAG criterion and level, severity, steps to reproduce (URL, number of Tab presses, selector), what a patient experiences, evidence (crop path), suggested fix as a short CSS or HTML snippet.
- `baseline_single_call(full_page_screenshot)`: Argon gets one full-page screenshot and returns JSON listing WCAG failures with types from our five bug categories plus "other".
- Draw a red box on crops (Pillow) before sending them to the scorer, so questions can refer to "the element in the red box".

## 6. Decision rule (`decide.py`)

- Confirmed: `proven` is true; or the scorer's probability is at or above `CONFIRM_P` (start at 0.80) for the failing answer AND a code check flagged a suspect for the same step.
- Needs a human: the scorer is between `HUMAN_LOW` (0.40) and `CONFIRM_P`, or the scorer flags a failure that code can't support.
- Dropped: below `HUMAN_LOW` and no code flag, or the replay fails to reproduce.
- One finding per (check, selector); keep the highest-evidence step.

## 7. Bug injector (`injector.py`)

`inject(page, bug_type, seed) -> manifest`. Pick the target with `random.Random(seed)` among tabbable elements visible in the first two viewports. Tag the target with `data-bs-target`. Manifest: `{url, bug_type, seed, target_selector, timestamp}`.

1. `hide_focus`: add style `[data-bs-target]:focus, [data-bs-target]:focus-visible { outline: none !important; box-shadow: none !important; }`
2. `keyboard_trap`: on the target, a keydown listener that calls `preventDefault()` on Tab and Shift+Tab and keeps focus on the target
3. `covering_banner`: when the target receives focus, place a `position: fixed` div exactly over its bounding rect, z-index 2147483647, with text "Special offer"
4. `positive_tabindex`: set `tabindex="1"` on a random element near the bottom of the page
5. `label_mismatch`: on a button or link with visible text, set `aria-label` to an unrelated phrase such as "Menu item"

Held-out protocol: build every page's manifest first, write it to `eval/heldout_manifest.json`, compute its SHA-256, show the hash on screen before running. Then run.

## 8. axe-core baseline (`axe_runner.py`)

- `page.add_script_tag(path="vendor/axe.min.js")`, then `page.evaluate("axe.run(document, {resultTypes: ['violations']})")`.
- Map rule IDs to our categories for scoring: `tabindex` maps to positive_tabindex, `label-content-name-mismatch` (experimental, enable it) maps to label_mismatch. axe has no rule for the other three by design. Be fair: report axe catches honestly.

## 9. Tickets and evidence (`tickets.py`)

- Evidence crop: the focused-state crop with a 3 px red box at the element rect, saved as PNG.
- Ticket file `runs/<id>/tickets/<n>.md` from Carbon's output plus the crop path and step index.

## 10. Replay (`replay.py`, self-contained)

- CLI: `python replay.py --url URL --tabs N --check CHECK [--inject-manifest FILE]`.
- Headless Chromium. Re-applies the injection if a manifest is given, presses Tab N times, runs the single named code check, prints JSON `{reproduced: bool, detail}`.
- Must have no imports from the rest of the repo, so it can run alone in the Managed Agent sandbox.
- `managed_agent.py`: for each confirmed finding, send the agent the script, the arguments and the instruction "install playwright and chromium, run this script, return only its JSON output". Run in the background; mark findings `replayed: true/false`. If the sandbox can't reach the site, send the saved snapshot (HAR) if available, else mark `replay: unavailable`.

## 11. Eval harness (`eval/harness.py`)

- Systems: `axe`, `single_gemini`, `code_only` (checks without the scorer or Argon), `blindspot` (full).
- Test sets:
  - `heldout`: stranger URLs from `submissions.jsonl`, each with one injected bug from the manifest
  - `govuk`: the GOV.UK accessibility tool audit test page (https://alphagov.github.io/accessibility-tool-audit/test-cases.html); score only the keyboard and focus cases
  - `w3c_clean`: W3C BAD "after" pages (https://www.w3.org/WAI/demos/bad/after/home.html and its siblings); every confirmed finding counts as a false flag
  - `dev`: vetted pages with injected bugs, for tuning before the freeze
- Metrics per system: injected bugs caught (by type and total), false flags on w3c_clean, median seconds per page, Gemini calls and an estimated cost per page.
- Output: `eval/results/results.json` and `eval/results/results.md` (the Markdown table the app shows).

## 12. App (`index.html`)

- Top: URL box, vetted-list dropdown, Run button, a "Break it" row with five bug buttons plus Random.
- Left: the live frame (latest full screenshot) and a step counter.
- Right: findings as they arrive. Each card has the crop with the red box, the WCAG criterion, the status (confirmed or needs a human) and a "View ticket" link.
- Below: axe-core's result for the same page, side by side with ours.
- A "Proof" tab rendering `results.md`, with the held-out manifest hash.
- Projector rules: large fonts, one big number per panel, crops zoomed so the element fills the card.
