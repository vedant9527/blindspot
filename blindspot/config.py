"""Thresholds and caps. Freeze at 2:00 PM; do not change after the freeze."""

MAX_TABS = 40
RUN_TIMEOUT_S = 60
PAGE_LOAD_TIMEOUT_MS = 15_000
STEP_WAIT_MS = 150
CROP_PADDING_PX = 12

FOCUS_DIFF_MIN = 3.0      # mean abs pixel diff (0-255) below this = no visible indicator
ORDER_JUMP_PX = 300       # upward jump larger than this = order suspect
MIN_TABBABLE = 5          # fewer = page treated as empty or blocked

CONFIRM_P = 0.80          # Decisions API probability to confirm (with code agreement)
HUMAN_LOW = 0.40          # below this and no code flag = dropped

DECISION_MODEL = "gemini-decision-1"
READER_MODEL = "gemini-4-hydrogen"
HARD_CALL_MODEL = "gemini-4-argon"
TICKET_MODEL = "gemini-4-carbon"
MANAGED_AGENT = "antigravity-preview-05-2026"
