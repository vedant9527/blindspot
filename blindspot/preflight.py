"""Preflight: load a page, handle cookie banners, detect blocks honestly.

Built at the event. Never bypasses bot protection: it only detects it and says so.
See docs/SPEC.md section 2.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from playwright.sync_api import Page, Response

from blindspot import config
from blindspot.browser import TABBABLE_COUNT_JS

BLOCK_TEXT = re.compile(
    r"just a moment|verify you are human|access denied|are you a robot|checking your browser|"
    r"unusual traffic|request blocked|attention required",
    re.I,
)
CHALLENGE_FRAMES = ("challenges.cloudflare.com", "google.com/recaptcha", "hcaptcha.com")
LOGIN_PATH = re.compile(r"(login|signin|sign-in|sso|/auth)", re.I)

BANNER_ORDER = [
    ("reject", re.compile(r"reject|decline|necessary only|only necessary|refuse", re.I), ["#onetrust-reject-all-handler"]),
    ("close", re.compile(r"^(close|dismiss|no thanks|x)$", re.I), []),
    ("accept", re.compile(r"accept|agree|allow|got it|^ok$", re.I), ["#onetrust-accept-btn-handler"]),
]


@dataclass
class PreflightResult:
    status: str  # "ok" or "blocked"
    reason: str = ""
    http_status: int | None = None
    tabbable: int = 0
    banner_action: str = "none"
    final_url: str = ""
    notes: list[str] = field(default_factory=list)


def dismiss_banner(page: Page) -> str:
    """Try reject, then close, then accept. Returns which one was clicked."""
    for action, pattern, selectors in BANNER_ORDER:
        for sel in selectors:
            try:
                loc = page.locator(sel).first
                if loc.is_visible(timeout=300):
                    loc.click(timeout=1000)
                    return f"{action} ({sel})"
            except Exception:
                pass
        try:
            loc = page.get_by_role("button", name=pattern).first
            if loc.is_visible(timeout=300):
                loc.click(timeout=1000)
                return action
        except Exception:
            pass
    return "none"


def detect_block(page: Page, response: Response | None, requested_url: str = "") -> tuple[bool, str]:
    """Return (blocked, reason) using code signals only."""
    status = response.status if response else None
    if status in (403, 429, 503):
        return True, f"HTTP {status}"
    for frame in page.frames:
        if any(host in frame.url for host in CHALLENGE_FRAMES):
            return True, "bot check (challenge widget)"
    try:
        text = page.evaluate("() => (document.body ? document.body.innerText : '').slice(0, 5000)")
    except Exception:
        text = ""
    if BLOCK_TEXT.search(text or ""):
        return True, "bot check (challenge page text)"
    final_path = urlparse(page.url).path
    requested_path = urlparse(requested_url).path if requested_url else ""
    if LOGIN_PATH.search(final_path) and not LOGIN_PATH.search(requested_path):
        return True, "login wall (redirected to a login page)"
    try:
        if page.locator("input[type=password]").count() > 0:
            return True, "login wall (password field)"
    except Exception:
        pass
    return False, ""


def run_preflight(page: Page, url: str) -> PreflightResult:
    """Load the page and decide whether Blindspot can test it."""
    try:
        response = page.goto(url, timeout=config.PAGE_LOAD_TIMEOUT_MS, wait_until="domcontentloaded")
    except Exception as exc:  # timeout, DNS failure, TLS error
        return PreflightResult(status="blocked", reason=f"page did not load ({type(exc).__name__})", final_url=url)
    try:
        page.wait_for_load_state("networkidle", timeout=2000)
    except Exception:
        pass
    result = PreflightResult(status="ok", http_status=response.status if response else None, final_url=page.url)
    blocked, reason = detect_block(page, response, url)
    if blocked:
        result.status, result.reason = "blocked", reason
        return result
    result.banner_action = dismiss_banner(page)
    result.tabbable = page.evaluate(TABBABLE_COUNT_JS)
    if result.tabbable < config.MIN_TABBABLE:
        result.status, result.reason = "blocked", f"only {result.tabbable} focusable elements"
    return result
