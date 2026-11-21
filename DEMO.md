# Blindspot demo kit

Built at the Gemini 4 NYC Hackathon, Nov 21 2026. Live judging: 3 minutes demo + 2 minutes Q&A. Scoring: Live demo on real, unrehearsed inputs 35% · Proof it works 25% · Creativity 20% · Gemini 4 and Decisions API use 20%.

## Before you walk up (5 minutes)

1. Laptop plugged in, lid open, on the venue Wi-Fi. Server up: `http://localhost:8000/api/health` says ok.
2. Tab A: run **mountsinai.org/find-a-doctor** with **No bug** now, so its tickets (and ideally a "Replayed by Managed Agent ✓" pill) are on screen before you start.
3. Tab B: **nyulangone.org/doctors** selected, Break it on **No bug**, ready to press Run.
4. Tab C: the GitHub repo README (results table and "Built at the event").
5. Close Discord, Slack and notifications. Browser zoom so the page fills the projector.

## 3-minute live demo

| Time | Do | Say |
|---|---|---|
| 0:00-0:25 | Tab B on screen | "By May 11, 2027, every hospital and health app that takes federal money must meet WCAG 2.1 AA under HHS Section 504. Many patients can't use a mouse: they press Tab, or a screen reader reads the page aloud. The standard scanner, axe-core, reads code, so it misses what only shows up on screen. I built Blindspot today: it uses the site like that patient and proves where they get stuck." |
| 0:25-0:40 | Hand a judge the Break it row: "Pick any bug." Then press Run. | "This is a live public site. You pick the bug; Blindspot plants it in our copy of the page, not on their server, and doesn't know which one you chose." |
| 0:40-1:20 | Point at the frame and caption while it tabs | "It presses Tab like a patient. At every step code proves what it can: pixels before and after focus, what's covering the element, the screen-reader name. Gemini 4 Hydrogen reads each frame, and the Gemini Decisions API answers each WCAG question with a confidence. Nothing is confirmed on a model's word alone: code has to prove it, or code has to suspect it and the Decisions API has to be at least 80% sure. Everything else goes to 'needs a human'." |
| 1:20-1:45 | Switch to Tab A (Mount Sinai ticket) | "On a real hospital site, no bug planted: Mount Sinai's accessibility widget replaces 25 link names, so a blind patient on 'Find a Doctor' hears 'press alt and 1'. axe-core missed it." |
| 1:45-2:15 | Back to Tab B: the judge's bug is caught; open the ticket | "There's your bug: red box on the exact element, the WCAG rule, what the patient experiences, and a code fix written by Gemini 4 Carbon. A Gemini Managed Agent now re-runs it in Google's sandbox to confirm it independently. axe-core on the same page: missed it." (If the replay pill is still spinning, say it takes about 90 seconds; don't wait.) |
| 2:15-2:50 | Click the footer / Proof | "Proof: 16 sites strangers submitted here today. I sealed the test with a SHA-256 hash and committed it before running anything. Blindspot caught 12 of 13 planted bugs, code alone 10, axe-core 5 of 12, one Gemini call on a screenshot 0, and Blindspot raised 0 false flags on W3C's clean pages. Four sites block bots; we report them, we don't sneak past." |
| 2:50-3:00 | | "From finding to fixing, for the patients who need it most. Happy to take any URL you want to try." |

If a run fails live (Wi-Fi or a blocked site): say "this is why we report blocks honestly", switch to Tab A, and show the Loom video as backup.

## 1-minute submission video (Loom, Screen + Cam, browser window only)

| Time | Screen | Say |
|---|---|---|
| 0:00-0:08 | Tab B: press Run with Hide focus planted | "I built Blindspot today. By May 2027, hospitals taking federal money must work for disabled patients, many of whom navigate with only the Tab key or a screen reader." |
| 0:08-0:25 | Live frame tabbing | "Blindspot presses Tab like that patient. Code proves what it can, Gemini 4 Hydrogen reads each frame, and the Decisions API scores every WCAG check with a confidence." |
| 0:25-0:37 | Tab A: Mount Sinai ticket | "On Mount Sinai it found an accessibility widget that replaces 25 link names, so a blind patient hears 'press alt 1' instead of 'Find a Doctor'." |
| 0:37-0:50 | Tab B: caught bug and ticket | "Our planted bug: caught, with a ticket and fix written by Gemini 4 Carbon, and replayed by a Gemini Managed Agent in Google's sandbox. axe-core missed it." |
| 0:50-1:00 | Proof | "On 16 sites strangers picked, sealed before running: Blindspot 12 of 13, axe-core 5 of 12, one Gemini screenshot call 0." |

## Q&A answers (one breath each)

- **"How do you know it isn't just guessing?"** A finding is confirmed only if code proves it (pixels, coverage, the browser's own accessibility tree) or code suspects it and the Decisions API is 80%+ sure. Everything else is "needs a human", and a Managed Agent replays confirmed findings in a separate sandbox.
- **"What if a site blocks you?"** We detect bot walls, 403s and logins and report the page as blocked. We never use stealth tricks. Four held-out sites dropped for that and are listed in the results.
- **"Why not just use axe-core?"** We run it side by side. It caught 5 of 12 planted bugs: it has no rule for invisible focus, keyboard traps or covered focus, because those only exist on screen.
- **"Why is Gemini needed if code catches most?"** On unseen sites, code alone caught 10 of 13; adding Gemini raised it to 12 of 13 with 0 extra false flags. Gemini also writes the tickets and fixes.
- **"Did you tune on the test?"** No. Thresholds froze at 2:57 PM; the held-out manifest's hash is in the commit before the run; the run happened once.
- **"What can't it do?"** It covers 5 keyboard and focus failure types, not all of WCAG, so it doesn't certify compliance. Public pages only, no patient portals behind logins yet. Planted bugs target the first screen so the 40-Tab run reaches them.
- **"Who uses this?"** Hospital and health-app teams racing the May 2027 deadline: they paste a page, get ready-to-fix tickets (Copy Markdown into Jira), fix, and re-run to verify.
- **"What did you build today?"** Everything except the planning docs; the README's "Built at the event" section lists it phase by phase, and the git history shows it.
