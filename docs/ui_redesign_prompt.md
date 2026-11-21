# UI redesign prompt for Antigravity (paste only after Step 8 is committed)

Merged from two agentic-council reviews (Artisan: visual design, Advocate: UX and demo flow).

```text
Redesign app/static/index.html only (vanilla HTML/CSS/JS, one file). Do not change any Python, config.py, eval files, or the server; do not restart port 8000 (static files reload on refresh). Keep every existing API call and SSE event working. Time box: 35 minutes.

Goal: the page must read as "an agent producing evidence tickets", not a stats dashboard (dashboards are banned by the hackathon rules), and be readable from the back of a room on a projector at 1280x800.

LAYOUT (1280x800, no scrolling needed during a run):
- Top bar, 56px: wordmark "Blindspot"; headline "We press Tab through hospital websites like a keyboard or screen-reader patient, and prove where they get stuck."; vetted-page dropdown with mountsinai.org/find-a-doctor preselected (then the three stable pages, then the rest); a small "or paste a URL" input; Run button; right-side chip "WCAG 2.1 AA · HHS 504 deadline May 2027"; "Proof" as a text link. Move "Submit URL (n)" into the Proof tab.
- Break-it strip, 48px, one row: label "Break it: plant one bug on this live site", chips: No bug (real site), Hide focus, Keyboard trap, Covering banner, Positive tabindex, Label mismatch, Random.
- Hero row, about 600px: LEFT 58% is the live keyboard frame (16:10) with an overlay "TAB 12 / 40" (48px mono) and a thin progress bar; under it a 24-28px caption: Tab 12 · Screen reader says: "<accessible name>, <role>". RIGHT 42% is the newest ticket fully expanded inline (no modal); earlier tickets collapse into one-line rows (title + WCAG) below it.
- Bottom strip, 64px, one sentence, e.g. "Planted: Hide focus · Blindspot caught it · axe-core missed it (no rule for this)". After a run, also show "Planted bugs caught on the dev set: Blindspot 10/10 · axe-core 4/10 · single-screenshot Gemini 0/10".
- DELETE: the KPI tile row, the bottom comparison grid (axe moves to one line per ticket and the full list to the Proof tab), and machine text on the main screen (page_state, Scorer p=, Gemini calls, selectors in captions, "Preflight OK"). Replace status text with plain words: "Loading the page…", "Tabbing like a patient…", "Writing tickets…", "Done".

TICKET CARD (the product):
- White card, 1px #D1D5DB border, 8px radius, 6px left border: #C8102E for confirmed, #B45309 for needs-a-human. No tinted backgrounds.
- Row 1: ticket ID (e.g. BS-014, mono), dark chip with WCAG number and name (e.g. "2.4.7 Focus Visible"), status "CONFIRMED" plus "Replayed ✓" if replayed, or "Replaying in Google sandbox…" while pending.
- Title, 32px: plain-language problem (e.g. "Keyboard users lose the cursor on Book appointment").
- Crop: full card width, about 220px tall, with the red evidence box.
- What the patient experiences: one 20px sentence with a 4px dark left rule. Label mismatch: A screen-reader patient on "{visible text}" hears "{accessible name}" instead. Trap: "A keyboard patient gets stuck here and can't reach anything below." Use the ticket text for others.
- Fix: 1-3 lines in a #F3F4F6 mono block. Footer: "Tab {n}", selector in small muted mono, "Copy Markdown" button.
- axe line: "axe-core on the same page: missed it, it has no rule for this." or "axe-core on the same page: also caught it."
- Group duplicates: same check + same accessible name collapse into one card with a count (e.g. "25 links").
- needs_human findings: hide the cards; show one line "3 more need a human look" that expands on click.
- Render incrementally: add or update cards by key, never rebuild all cards via innerHTML (stops flicker and scroll resets on SSE events and replay polling). Newest ticket goes on top, flashes once for 2s, and stays in view.

VISUAL SYSTEM:
- Fonts: Atkinson Hyperlegible (UI, from Google Fonts; designed by the Braille Institute) and JetBrains Mono (steps, WCAG codes, fixes).
- Colors: background #F7F5F0, surface #FFFFFF, text #111827, muted #4B5563, border #D1D5DB, brand and focus #3730A3, evidence red #C8102E (only for evidence and confirmed), needs-human #B45309, frame background #111827. Selected Break-it chip: solid #111827 with white text, not red.
- Type scale 16/20/24/32/48; html { font-size: clamp(16px, 1.25vw, 24px) } so it scales to 1920.
- Evidence box: 4px solid #C8102E with box-shadow 0 0 0 2px #fff and a small red label tab "FOCUS IS HERE".
- The page itself must be accessible: visible focus everywhere (3px #3730A3 outline, 3px offset; #FBBF24 on dark surfaces), contrast 4.5:1 or more, real buttons, aria-live="polite" on the status caption.

WOW MOMENT (about 20 lines of JS): when a confirmed finding arrives, draw the red box on the frame (300ms), clone the crop and fly it into the ticket pane (transform transition, 450ms, cubic-bezier(.2,.8,.2,1)), then fade the ticket sections in 60ms apart, and flip the bottom strip to the axe result. Under prefers-reduced-motion, swap everything in instantly with no movement.

When done, run one demo on mountsinai.org/find-a-doctor with No bug, then one on nyulangone.org/doctors with Keyboard trap, and tell me what is on screen at the end of each. Don't run git commit or git push; I commit from another tool.
```
