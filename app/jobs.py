from datetime import datetime
import re
from time import monotonic
from pathlib import Path

from rq import get_current_job
from playwright.sync_api import sync_playwright


DEBUG_DIR = Path("data/debug_meetings")
CDP_ENDPOINT = "http://127.0.0.1:9222"
PREJOIN_TIMEOUT_MS = 45_000
PAGE_TIMEOUT_MS = 30_000
POSTJOIN_TIMEOUT_MS = 45_000


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    return slug or "meeting"


def _log(message: str):
    print(f"[meet-job] {message}", flush=True)


def _update_job_meta(stage: str, detail: str | None = None):
    job = get_current_job()
    if not job:
        return

    job.meta["stage"] = stage
    if detail is not None:
        job.meta["detail"] = detail
    job.save_meta()


def _first_visible(locator):
    if locator.count() == 0:
        return None

    for index in range(locator.count()):
        candidate = locator.nth(index)
        try:
            if candidate.is_visible():
                return candidate
        except Exception:
            continue

    return None


def _is_in_meeting(page) -> bool:
    leave_button = _first_visible(page.get_by_role("button", name="Leave call"))
    if leave_button:
        return True

    leave_text = _first_visible(page.get_by_text("Leave call"))
    if leave_text:
        return True

    return False


def _profile_needs_sign_in(page) -> bool:
    if "accounts.google.com" in page.url:
        return True

    if page.get_by_text("Couldn't sign you in").count() > 0:
        return True

    if page.get_by_text("Sign in").count() > 0 and page.get_by_text("Getting ready").count() > 0:
        return True

    return False


def _wait_for_prejoin_controls(page, timeout_ms: int = 90000) -> str:
    blocked_text = "You can't join this video call"
    join_candidates = [
        page.get_by_role("button", name=re.compile(r"^Join( now)?$")),
        page.locator('button:has-text("Join now")'),
        page.locator('button:has-text("Join")'),
    ]
    ask_candidates = [
        page.get_by_role("button", name="Ask to join"),
        page.locator('button:has-text("Ask to join")'),
    ]

    started_at = monotonic()
    last_reported_bucket = -1

    for _ in range(timeout_ms // 500):
        elapsed_seconds = int(monotonic() - started_at)
        report_bucket = elapsed_seconds // 5
        if report_bucket != last_reported_bucket:
            last_reported_bucket = report_bucket
            _log(f"waiting for Meet controls ({elapsed_seconds}s elapsed)")
            _update_job_meta("waiting_prejoin", f"{elapsed_seconds}s elapsed")

        if _is_in_meeting(page):
            return "joined"

        if page.get_by_text(blocked_text).count() > 0:
            return "blocked"

        for candidate in join_candidates + ask_candidates:
            if _first_visible(candidate):
                return "ready"

        page.wait_for_timeout(500)

    return "timeout"


def _handle_media_prompt(page) -> bool:
    prompt_text = "Do you want people to see and hear you in the meeting?"
    if page.get_by_text(prompt_text).count() == 0:
        return False

    continue_button = _first_visible(
        page.get_by_role("button", name="Continue without microphone and camera")
    )
    if continue_button:
        _log("dismissing mic/camera prompt")
        _update_job_meta("dismissing_media_prompt")
        continue_button.click()
        return True

    allow_button = _first_visible(
        page.get_by_role("button", name="Allow microphone and camera")
    )
    if allow_button:
        _log("allowing mic/camera prompt")
        _update_job_meta("allowing_media_prompt")
        allow_button.click()
        return True

    return False


def _wait_for_join_completion(page, timeout_ms: int = POSTJOIN_TIMEOUT_MS) -> str:
    start = monotonic()
    last_reported_bucket = -1

    for _ in range(timeout_ms // 500):
        elapsed_seconds = int(monotonic() - start)
        report_bucket = elapsed_seconds // 5
        if report_bucket != last_reported_bucket:
            last_reported_bucket = report_bucket
            _log(f"waiting for join completion ({elapsed_seconds}s elapsed)")
            _update_job_meta("waiting_postjoin", f"{elapsed_seconds}s elapsed")

        if _is_in_meeting(page):
            return "joined"

        if page.get_by_text("You can't join this video call").count() > 0:
            return "blocked"

        if _handle_media_prompt(page):
            continue

        if page.get_by_text("Connecting...").count() > 0:
            page.wait_for_timeout(500)
            continue

        if page.get_by_text("Connecting").count() > 0:
            page.wait_for_timeout(500)
            continue

        page.wait_for_timeout(500)

    return "timeout"


def _write_debug_artifacts(page, title: str, reason: str):
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = _safe_slug(title)
    base = DEBUG_DIR / f"{stamp}_{slug}"

    artifacts = {"reason": reason}

    screenshot_path = base.with_suffix(".png")
    try:
        page.screenshot(path=str(screenshot_path), full_page=True)
        artifacts["screenshot"] = str(screenshot_path)
    except Exception:
        pass

    html_path = base.with_suffix(".html")
    try:
        html_path.write_text(page.content(), encoding="utf-8")
        artifacts["html"] = str(html_path)
    except Exception:
        pass

    text_path = base.with_suffix(".txt")
    try:
        text = page.locator("body").inner_text(timeout=2000)
        text_path.write_text(text, encoding="utf-8")
        artifacts["text"] = str(text_path)
    except Exception:
        pass

    return artifacts


def join_meeting_job(meeting_url: str, title: str):
    _log(f"job started for: {title}")
    _log(f"meeting url: {meeting_url}")
    _update_job_meta("starting", meeting_url)

    with sync_playwright() as p:
        _update_job_meta("connecting_browser")
        _log(f"connecting to Chrome at {CDP_ENDPOINT}")
        try:
            browser = p.chromium.connect_over_cdp(CDP_ENDPOINT)
        except Exception as error:
            _update_job_meta("browser_not_running", str(error))
            return {
                "title": title,
                "meeting_url": meeting_url,
                "status": "browser_not_running",
                "reason": f"Start the bot browser first: {error}",
            }

        if not browser.contexts:
            _update_job_meta("browser_not_ready")
            return {
                "title": title,
                "meeting_url": meeting_url,
                "status": "browser_not_ready",
                "reason": "No browser context available on the running Chrome session",
            }

        context = browser.contexts[0]
        _update_job_meta("browser_connected")
        _log(f"using browser context with {len(context.pages)} open page(s)")
        page = context.new_page()
        _log("created worker page")
        keep_page_open = False

        try:
            _update_job_meta("loading_meet_home")
            _log("loading meet home")
            page.goto("https://meet.google.com", wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
            _log(f"meet home loaded: {page.url}")

            if _profile_needs_sign_in(page):
                debug = _write_debug_artifacts(
                    page,
                    title,
                    "Chrome profile is not signed into Google Meet",
                )
                _update_job_meta("needs_sign_in", "Chrome profile is not signed into Google Meet")
                return {
                    "title": title,
                    "meeting_url": meeting_url,
                    "status": "needs_sign_in",
                    "reason": "Chrome profile is not signed into Google Meet",
                    "debug": debug,
                }

            if "?" in meeting_url:
                meeting_url += "&hl=en"
            else:
                meeting_url += "?hl=en"

            _update_job_meta("loading_meeting")
            _log("loading meeting url")
            page.goto(meeting_url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
            _log(f"meeting page loaded: {page.url}")

            _update_job_meta("waiting_prejoin", "0s elapsed")
            wait_state = _wait_for_prejoin_controls(page, timeout_ms=PREJOIN_TIMEOUT_MS)
            if wait_state == "joined":
                _update_job_meta("joined", "already inside meeting")
                keep_page_open = True
                return {
                    "title": title,
                    "meeting_url": meeting_url,
                    "status": "joined",
                    "reason": "Bot was already inside the meeting",
                }

            if wait_state == "blocked":
                _update_job_meta("blocked", "You can't join this video call")
                return {
                    "title": title,
                    "meeting_url": meeting_url,
                    "status": "blocked",
                    "reason": "You can't join this video call",
                }

            name_input = page.get_by_label("Your name")
            if name_input.count() > 0 and name_input.first.is_visible():
                name_input.first.fill("Hisham Jr.")

            clicked = False
            join_candidates = [
                page.get_by_role("button", name=re.compile(r"^Join( now)?$")),
                page.locator('button:has-text("Join now")'),
                page.locator('button:has-text("Join")'),
            ]
            ask_candidates = [
                page.get_by_role("button", name="Ask to join"),
                page.locator('button:has-text("Ask to join")'),
            ]

            for candidate in join_candidates:
                visible = _first_visible(candidate)
                if visible:
                    _log("clicking join button")
                    _update_job_meta("join_clicked")
                    visible.click()
                    clicked = True
                    break

            if not clicked:
                for candidate in ask_candidates:
                    visible = _first_visible(candidate)
                    if visible:
                        _log("clicking ask-to-join button")
                        _update_job_meta("ask_to_join_clicked")
                        visible.click()
                        clicked = True
                        break

            if not clicked:
                debug = _write_debug_artifacts(
                    page,
                    title,
                    "No join button found on the Meet prejoin page",
                )
                _update_job_meta("failed", "No join button found on the Meet prejoin page")
                return {
                    "title": title,
                    "meeting_url": meeting_url,
                    "status": "failed",
                    "reason": "No join button found on the Meet prejoin page",
                    "debug": debug,
                }

            postjoin_state = _wait_for_join_completion(page, timeout_ms=POSTJOIN_TIMEOUT_MS)
            if postjoin_state == "joined":
                _update_job_meta("joined", "meeting UI detected after click")
                keep_page_open = True
                return {
                    "title": title,
                    "meeting_url": meeting_url,
                    "status": "joined",
                }

            if postjoin_state == "blocked":
                debug = _write_debug_artifacts(
                    page,
                    title,
                    "Blocked after join click",
                )
                _update_job_meta("blocked", "Blocked after join click")
                return {
                    "title": title,
                    "meeting_url": meeting_url,
                    "status": "blocked",
                    "reason": "Blocked after join click",
                    "debug": debug,
                }

            debug = _write_debug_artifacts(
                page,
                title,
                "Clicked a join control but never detected the in-meeting state",
            )
            _update_job_meta("failed", "Clicked a join control but never detected the in-meeting state")
            return {
                "title": title,
                "meeting_url": meeting_url,
                "status": "failed",
                "reason": "Clicked a join control but never detected the in-meeting state",
                "debug": debug,
            }
        except Exception as error:
            debug = None
            try:
                debug = _write_debug_artifacts(page, title, str(error))
            except Exception:
                pass
            _update_job_meta("failed", str(error))
            _log(f"job failed: {error}")
            return {
                "title": title,
                "meeting_url": meeting_url,
                "status": "failed",
                "reason": str(error),
                "debug": debug,
            }
        finally:
            if not keep_page_open:
                try:
                    page.close()
                except Exception:
                    pass
            else:
                _log("leaving the meeting tab open so the bot stays connected")
