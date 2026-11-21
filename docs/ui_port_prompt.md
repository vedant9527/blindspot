# UI port prompt for Antigravity (mockup -> real app)

Mockup source: ~/blindspot-mockups/index.html (screenshots: ~/blindspot-mockups/state1-4.png).
Council review: Artisan 7/10 (visual), Advocate 6/10 (demo-readiness). Changes below fold in both.

```text
Port the approved mockup into the real app. Source: ~/blindspot-mockups/index.html (look at ~/blindspot-mockups/state1.png to state4.png for Idle, Running, Finding landed, Done). Reuse its CSS custom properties, fonts, layout and ticket markup in app/static/index.html, wired to the real API and SSE events (preflight, step, finding, axe, ticket, done, error, plus /api/run/{id} polling for replay and /api/proof). Only edit app/static/index.html. Do not touch Python, config.py, eval files or the server, and do not restart port 8000. Time box: 35 minutes; if short on time, do items 1-6 first.

Changes on top of the mockup, in priority order:
1. Fit 1280x800 with no horizontal clipping: body{margin:0}; .app{width:100%;max-width:1280px;margin:0 auto;box-sizing:border-box}; main grid columns minmax(0,1.1fr) minmax(0,1fr); header{flex-wrap:wrap}. Remove the 3-line tagline from the header (the idle caption says it). Remove the "State 1-4" switcher.
2. Run button: color:#fff; font-weight:700; larger. Make the paste-URL input wider (judges will type their own URLs). Every interactive element gets :focus-visible{outline:3px solid #3730A3;outline-offset:3px} (#FBBF24 on dark surfaces). Raise any small grey text to at least 16px and #4B5563 or darker; the dimmed neighbours in the crop go to #6b7280 at least.
3. Real data must not break the layout: ticket title clamps to 2 lines (-webkit-line-clamp:2); narration caption clamps to 3 lines; URLs and selectors use white-space:nowrap;overflow:hidden;text-overflow:ellipsis with a title attribute; dropdown max-width:260px. Live frame shows the real step screenshot (object-fit:cover; object-position:top) with the red FOCUS IS HERE box positioned in percentages from the step rect and the screenshot size. Ticket crop uses the real focused crop at 1:1, fixed height about 160px, centered on the element.
4. Honest states (all from real events, never hardcoded):
   - Counter: "TAB 14" with "max 40" in small text (we don't know the total in advance).
   - Replay pill, three states: "Replaying in Google Managed Agent sandbox… 0:47" (spinner, counting up), "Replayed by Managed Agent ✓", or "Replay didn't finish; evidence is from the live run". Never show Replayed ✓ before the replay result arrives.
   - Blocked site: "This site blocks automated browsers, so nothing was tested. We don't bypass bot protection." with a button "Try a vetted page".
   - Error: "Stopped at Tab 9: the page stopped responding. Findings so far are kept."
   - needs_human: amber ticket "Needs a human look · confidence 0.58"; the "N more need a human look" row expands to these.
   - axe line comes from the real axe event for that page: "axe-core on the same page: missed it, it has no rule for this." or "also caught it."
5. Make Gemini visible without a dashboard: one small mono line on each ticket built from real fields, e.g. "Hydrogen read frame 14 → Decisions API 'Focus visible?' no, 0.94 → Carbon wrote this ticket". If a field is missing (code-proven finding with no scorer call), say "Proven by code check → Carbon wrote this ticket". Next to CONFIRMED add "proven by code" or "code + Decisions API" from decision_reason.
6. Footer = Proof, one click: turn the bottom strip into a button that opens the Proof tab, text from /api/proof results: "Held-out, 16 stranger sites, sealed sha256 816e4bb1…: Blindspot 12/13 · without Gemini 10/13 · axe-core 5/12 · Gemini one screenshot 0/13". During a run it shows the planted-bug sentence instead. Footer font-size 22px.
7. Copy: Break-it label "Break it: plant one bug in our copy of this page" (we never change the real site). Keep the chip "WCAG 2.1 AA · HHS 504 deadline May 2027" (verified: extended to May 11, 2027 for 15+ employees).

Keep exactly: the red FOCUS IS HERE label in both the live frame and the ticket crop, and the big TAB counter. Group duplicate findings (same check + same accessible name) into one ticket with a count, newest ticket on top, earlier ones collapsed; render incrementally (no full innerHTML rebuilds).

When done: hard-refresh http://localhost:8000 (static file, no restart needed), run mountsinai.org/find-a-doctor with No bug, then nyulangone.org/doctors with Hide focus, and tell me what's on screen at the end of each, including whether anything clips at 1280x800. Don't run git commit or git push; I commit from another tool.
```
