"""Thresholds and caps. Freeze at 2:00 PM; do not change after the freeze."""

MAX_TABS = 40
RUN_TIMEOUT_S = 60
PAGE_LOAD_TIMEOUT_MS = 15_000
STEP_WAIT_MS = 150
CROP_PADDING_PX = 12

FOCUS_DIFF_MIN = 3.0      # mean abs pixel diff (0-255) below this = no visible indicator
ORDER_JUMP_PX = 300       # upward jump larger than this = order suspect
MIN_TABBABLE = 5          # fewer = page treated as empty or blocked

PIXEL_DELTA = 24          # a pixel "changed" if any channel differs by more than this (0-255)
FOCUS_CHANGED_PX_MIN = 8  # fewer changed pixels in the crop = no indicator at all (proven)
ELSEWHERE_PX_MAX = 200    # more changed pixels outside the crop = focus style may be elsewhere (suspect, not proven)
INDICATOR_CONTRAST_MIN = 3.0  # WCAG 1.4.11 non-text contrast
RING_MAX_FRACTION = 0.5   # judge indicator contrast only when under half the crop changed (a ring, not a region)
OFFSCREEN_RECHECK_MS = 300    # wait before trusting an off-screen focus position (animations)
TRAP_WINDOW = 10          # look at this many recent steps for a trap
TRAP_MAX_DISTINCT = 2     # at most this many distinct elements in the window = trap suspect
TRAP_MIN_TABBABLE = 10    # only judge traps on pages with at least this many tabbable elements
MAX_POPUP_CLOSES = 2      # popups closed per run (logged); more than that and we test what is there

CONFIRM_P = 0.80          # Decisions API probability to confirm (with code agreement)
HUMAN_LOW = 0.40          # below this and no code flag = dropped

GEMINI_TIMEOUT_S = 8.0    # per-call timeout (converted to ms for google-genai HttpOptions)
GEMINI_RETRIES = 2        # attempts per key before falling back or failing
SCORER_WORKERS = 12       # thread-pool workers for parallel Hydrogen + Decisions calls
RED_BOX_WIDTH_PX = 3      # red marker box stroke width on scorer/evidence crops
BOX_OUTSET_PX = 8         # CSS-pixel gap outside element rect so red box never hides focus rings
SCORER_CONTEXT_PAD_PX = 48  # CSS-pixel context padding around element rect for scorer crops

DECISION_MODEL = "gemini-decision-1"
READER_MODEL = "gemini-4-hydrogen"
HARD_CALL_MODEL = "gemini-4-argon"
TICKET_MODEL = "gemini-4-carbon"
MANAGED_AGENT = "antigravity-preview-05-2026"
