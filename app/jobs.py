from datetime import datetime
import re
from time import monotonic
from pathlib import Path

from rq import get_current_job
from playwright.sync_api import sync_playwright

from app.meeting_ai import MeetingAISession
from app.ntfy_client import send_meeting_report
from app.task_queue import queue


DEBUG_DIR = Path("data/debug_meetings")
CDP_ENDPOINT = "http://127.0.0.1:9222"
PREJOIN_TIMEOUT_MS = 45_000
PAGE_TIMEOUT_MS = 30_000
POSTJOIN_TIMEOUT_MS = 45_000
MONITOR_POLL_MS = 10_000
ALONE_GRACE_SECONDS = 30
ASSISTANT_CHAT_MESSAGES = [
    "Hello Guys, I am the assistant bot of Hisham, he is currently unable to join the meeting (fixing portal travel)",
    "I will do my best to represent him",
    "Just mention my name and I will do my best to help you, Thanks!",
]


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


def _set_job_meta_value(key: str, value):
    job = get_current_job()
    if not job:
        return

    job.meta[key] = value
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


def _ensure_microphone_muted(page) -> bool:
    if _find_visible_button_by_patterns(
        page,
        [
            r"turn on microphone",
            r"unmute microphone",
            r"microphone is off",
            r"mic is off",
        ],
    ):
        return True

    mic_button = _find_visible_button_by_patterns(
        page,
        [
            r"turn off microphone",
            r"mute microphone",
            r"microphone is on",
            r"mic is on",
            r"microphone",
            r"\bmic\b",
        ],
    )
    if not mic_button:
        mic_button = _first_visible(
            page.get_by_role("button", name=re.compile(r"microphone|mic", re.I))
        )

    if not mic_button:
        return False

    try:
        _log("muting microphone")
        _update_job_meta("muting_microphone")
        mic_button.click()
        page.wait_for_timeout(500)
        return bool(
            _find_visible_button_by_patterns(
                page,
                [
                    r"turn on microphone",
                    r"unmute microphone",
                    r"microphone is off",
                    r"mic is off",
                ],
            )
        )
    except Exception:
        return False


def _body_text(page) -> str:
    try:
        return page.locator("body").inner_text(timeout=2000).lower()
    except Exception:
        return ""


def _body_text_raw(page) -> str:
    try:
        return page.locator("body").inner_text(timeout=2000)
    except Exception:
        return ""


def _meeting_code_from_url(meeting_url: str) -> str | None:
    match = re.search(r"meet\.google\.com/([a-z0-9-]+)", meeting_url)
    if match:
        return match.group(1)

    return None


def _find_meeting_page(context, meeting_url: str):
    meeting_code = _meeting_code_from_url(meeting_url)
    normalized_url = meeting_url.split("?")[0].rstrip("/")

    for page in context.pages:
        try:
            page_url = page.url.split("?")[0].rstrip("/")
        except Exception:
            continue

        if meeting_code and meeting_code in page_url:
            return page

        if page_url == normalized_url:
            return page

    return None


def _probe_people_panel(page) -> bool:
    people_button = _first_visible(page.get_by_role("button", name=re.compile(r"^People$", re.I)))
    if not people_button:
        return False

    body_text = _body_text(page)
    if re.search(r"\bcontributors\b\s*0\b", body_text, re.I):
        return True

    opened_here = False
    try:
        _log("probing people panel for participant count")
        people_button.click()
        opened_here = True
        page.wait_for_timeout(1200)

        panel_text = _body_text(page)
        if re.search(r"\bcontributors\b\s*1\b", panel_text, re.I):
            return True

        if re.search(r"\bin the meeting\b[\s\S]{0,120}\b1\b", panel_text, re.I):
            return True

        if re.search(r"\bonly you\b", panel_text, re.I):
            return True

        return False
    finally:
        if opened_here:
            try:
                people_button.click()
                page.wait_for_timeout(500)
            except Exception:
                pass


def _read_contributor_count(page):
    body_text = _body_text(page)
    patterns = [
        r"\bcontributors\b\s*(\d+)",
        r"\bin the meeting\b[\s\S]{0,120}\bcontributors\b\s*(\d+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, body_text, re.I)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                continue

    people_button = _first_visible(page.get_by_role("button", name=re.compile(r"^People$", re.I)))
    if not people_button:
        return None

    opened_here = False
    try:
        _log("reading contributor count from people panel")
        people_button.click()
        opened_here = True
        page.wait_for_timeout(1200)
        panel_text = _body_text(page)
        for pattern in patterns:
            match = re.search(pattern, panel_text, re.I)
            if match:
                try:
                    return int(match.group(1))
                except ValueError:
                    continue
    finally:
        if opened_here:
            try:
                people_button.click()
                page.wait_for_timeout(500)
            except Exception:
                pass

    return None


def _ensure_chat_panel_open(page, timeout_ms: int = 10_000):
    started_at = monotonic()
    last_click_at = 0

    while (monotonic() - started_at) * 1000 < timeout_ms:
        chat_input = _find_chat_input(page)
        if chat_input:
            return True

        chat_button = _first_visible(
            page.get_by_role("button", name=re.compile(r"^Chat with everyone$", re.I))
        )
        if not chat_button:
            chat_button = _first_visible(
                page.locator('button:has-text("Chat with everyone")')
            )

        if chat_button and (monotonic() - last_click_at) >= 1.5:
            _log("opening chat panel")
            try:
                chat_button.click()
                last_click_at = monotonic()
            except Exception:
                pass

        page.wait_for_timeout(500)

    return _find_chat_input(page) is not None


def _find_visible_button_by_patterns(page, patterns):
    buttons = page.locator("button")

    for index in range(buttons.count()):
        button = buttons.nth(index)
        try:
            if not button.is_visible():
                continue

            chunks = []
            for attr in ("aria-label", "title"):
                value = button.get_attribute(attr)
                if value:
                    chunks.append(value)

            try:
                inner_text = button.inner_text(timeout=500)
                if inner_text:
                    chunks.append(inner_text)
            except Exception:
                pass

            haystack = " ".join(chunks).strip()
            if not haystack:
                continue

            for pattern in patterns:
                if re.search(pattern, haystack, re.I):
                    return button
        except Exception:
            continue

    return None


def _ensure_captions_enabled(page):
    if _find_visible_button_by_patterns(page, [r"turn off captions", r"hide captions"]):
        return True

    captions_button = _first_visible(
        page.get_by_role("button", name=re.compile(r"captions?|cc", re.I))
    )
    if not captions_button:
        captions_button = _find_visible_button_by_patterns(
            page,
            [
                r"turn on captions",
                r"show captions",
                r"\bcaptions?\b",
                r"\bcc\b",
            ],
        )

    if not captions_button:
        return False

    try:
        _log("enabling captions")
        captions_button.click()
        page.wait_for_timeout(1800)
        return _find_visible_button_by_patterns(
            page, [r"turn off captions", r"hide captions"]
        ) is not None
    except Exception:
        return False


def _live_meeting_text(page) -> str:
    selectors = [
        '[aria-live="polite"]',
        '[aria-live="assertive"]',
        '[role="log"]',
        '[jsname="YSxpc"]',
        '[jsname="fna"]',
    ]

    chunks = []
    for selector in selectors:
        locator = page.locator(selector)
        for index in range(locator.count()):
            candidate = locator.nth(index)
            try:
                if not candidate.is_visible():
                    continue
                text = candidate.inner_text(timeout=800).strip()
                if text:
                    chunks.append(text)
            except Exception:
                continue

    if chunks:
        return "\n".join(chunks)

    return _body_text_raw(page)


def _find_chat_input(page):
    candidates = [
        page.get_by_role("textbox", name=re.compile(r"message", re.I)),
        page.get_by_role("textbox"),
        page.locator("textarea"),
        page.locator('[contenteditable="true"]'),
    ]

    for candidate in candidates:
        visible = _first_visible(candidate)
        if visible:
            return visible

    return None


def _send_chat_message(page, message: str) -> bool:
    chat_input = _find_chat_input(page)
    if not chat_input:
        if not _ensure_chat_panel_open(page):
            return False
        chat_input = _find_chat_input(page)
        if not chat_input:
            return False

    try:
        _log(f"sending chat message: {message}")
        chat_input.click()
        chat_input.fill(message)
        chat_input.press("Enter")
        page.wait_for_timeout(800)
        return True
    except Exception:
        try:
            chat_input.click()
            chat_input.press_sequentially(message)
            chat_input.press("Enter")
            page.wait_for_timeout(800)
            return True
        except Exception:
            return False


def _send_assistant_intro_messages(page, title: str, session: MeetingAISession | None = None) -> bool:
    _log("sending assistant intro messages")
    _update_job_meta("sending_assistant_messages", title)

    for message in ASSISTANT_CHAT_MESSAGES:
        if session is not None:
            session.mark_own_message(message)
        _set_job_meta_value("assistant_message", message)
        if not _ensure_chat_panel_open(page):
            _log("failed to open chat panel")
            return False
        ok = _send_chat_message(page, message)
        if not ok:
            _log("failed to send one of the assistant messages")
            return False
        page.wait_for_timeout(1200)

    _set_job_meta_value("assistant_messages_sent", True)
    _log("assistant intro messages sent")
    return True


def _answer_question_in_chat(page, session: MeetingAISession, question: str) -> bool:
    _log(f"answering question from meeting text: {question}")
    _update_job_meta("answering_question", question)

    try:
        answer = session.generate_answer(question)
    except Exception as error:
        _update_job_meta("answer_failed", str(error))
        _log(f"failed to generate answer: {error}")
        return False

    session.mark_answered(question)
    session.mark_own_message(answer)

    if not _send_chat_message(page, answer):
        _log("failed to send generated answer")
        return False

    _set_job_meta_value("last_answer", answer)
    _log("generated answer sent to chat")
    return True


def _maybe_answer_new_questions(page, session: MeetingAISession, contributor_count: int | None):
    if contributor_count is not None and contributor_count < 2:
        return

    raw_text = _live_meeting_text(page)
    if not raw_text.strip():
        return

    session.ingest_text(raw_text)
    for question in session.extract_answerable_questions(raw_text):
        if not session.should_answer(question):
            continue
        if _answer_question_in_chat(page, session, question):
            page.wait_for_timeout(1200)


def _finalize_meeting_ai(session: MeetingAISession, title: str):
    artifacts = session.finalize()
    if not artifacts:
        return None

    _update_job_meta("transcript_saved", artifacts["transcript_path"])
    _set_job_meta_value("meeting_summary", artifacts["summary"])
    _log("meeting transcript saved and summary generated")

    try:
        ntfy_result = send_meeting_report(
            title=title,
            transcript=artifacts["transcript"],
            summary=artifacts["summary"],
        )
        artifacts["ntfy"] = ntfy_result
        if ntfy_result.get("sent"):
            _update_job_meta("ntfy_sent", ntfy_result.get("topic"))
        else:
            _update_job_meta("ntfy_not_sent", ntfy_result.get("reason", "not configured"))
    except Exception as error:
        artifacts["ntfy"] = {"sent": False, "reason": str(error)}
        _update_job_meta("ntfy_failed", str(error))
        _log(f"failed to send meeting report via ntfy: {error}")

    return {
        "transcript_path": artifacts["transcript_path"],
        "summary": artifacts["summary"],
        "ntfy": artifacts.get("ntfy"),
    }


def _meeting_leave_reason(page):
    body_text = _body_text(page)

    ended_patterns = [
        r"meeting has ended",
        r"this video call has ended",
        r"you left the meeting",
    ]
    alone_patterns = [
        r"you're the only one here",
        r"you are the only one here",
        r"no one else is here",
        r"you're the last one here",
        r"1 participant",
        r"1 person",
        r"only you",
    ]

    for pattern in ended_patterns:
        if re.search(pattern, body_text, re.I):
            return "meeting_ended", pattern

    for pattern in alone_patterns:
        if re.search(pattern, body_text, re.I):
            return "alone", pattern

    if _probe_people_panel(page):
        return "alone", "people_panel_contributors_1"

    return None, None


def _click_leave_controls(page):
    leave_candidates = [
        page.get_by_role("button", name=re.compile(r"^Leave call$")),
        page.get_by_role("button", name=re.compile(r"^Leave meeting$")),
        page.get_by_role("button", name=re.compile(r"^End meeting for all$")),
        page.locator('button:has-text("Leave call")'),
        page.locator('button:has-text("Leave meeting")'),
        page.locator('button:has-text("End meeting for all")'),
    ]

    for candidate in leave_candidates:
        visible = _first_visible(candidate)
        if visible:
            _log("clicking leave control")
            visible.click()
            page.wait_for_timeout(1000)
            return True

    return False


def _leave_meeting(page):
    if page.is_closed():
        return

    _click_leave_controls(page)

    confirm_candidates = [
        page.get_by_role("button", name=re.compile(r"^Leave$")),
        page.get_by_role("button", name=re.compile(r"^Leave meeting$")),
        page.get_by_role("button", name=re.compile(r"^End meeting for all$")),
        page.locator('button:has-text("Leave")'),
        page.locator('button:has-text("Leave meeting")'),
        page.locator('button:has-text("End meeting for all")'),
    ]

    for candidate in confirm_candidates:
        visible = _first_visible(candidate)
        if visible:
            _log("confirming leave")
            visible.click()
            page.wait_for_timeout(1000)
            break


def _queue_monitor_job(meeting_url: str, title: str):
    try:
        monitor_job = queue.enqueue(
            monitor_meeting_job,
            meeting_url,
            title,
            job_timeout=60 * 60 * 12,
        )
        _log(f"queued leave monitor job {monitor_job.id}")
        _update_job_meta("monitor_queued", monitor_job.id)
        return monitor_job.id
    except Exception as error:
        _log(f"failed to queue leave monitor job: {error}")
        return None


def _wait_for_join_completion(page, timeout_ms: int = POSTJOIN_TIMEOUT_MS) -> str:
    start = monotonic()
    last_reported_bucket = -1

    for _ in range(timeout_ms // 500):
        _ensure_microphone_muted(page)

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


def monitor_meeting_job(meeting_url: str, title: str):
    _log(f"monitor started for: {title}")
    _log(f"monitoring meeting url: {meeting_url}")
    _update_job_meta("monitoring", meeting_url)

    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp(CDP_ENDPOINT)
        except Exception as error:
            _update_job_meta("monitor_browser_not_running", str(error))
            return {
                "title": title,
                "meeting_url": meeting_url,
                "status": "browser_not_running",
                "reason": f"Start the bot browser first: {error}",
            }

        if not browser.contexts:
            _update_job_meta("monitor_browser_not_ready")
            return {
                "title": title,
                "meeting_url": meeting_url,
                "status": "browser_not_ready",
                "reason": "No browser context available on the running Chrome session",
            }

        context = browser.contexts[0]
        page = _find_meeting_page(context, meeting_url)
        if not page:
            _update_job_meta("monitor_page_missing", "meeting tab not found")
            return {
                "title": title,
                "meeting_url": meeting_url,
                "status": "not_found",
                "reason": "Meeting tab was not found in the running Chrome session",
            }

        meeting_ai = MeetingAISession(title)
        _ensure_captions_enabled(page)
        _ensure_microphone_muted(page)
        alone_since = None
        job = get_current_job()
        assistant_messages_sent = bool(job and job.meta.get("assistant_messages_sent"))
        try:
            while True:
                if page.is_closed():
                    final_artifacts = _finalize_meeting_ai(meeting_ai, title)
                    _update_job_meta("left", "meeting tab closed")
                    result = {
                        "title": title,
                        "meeting_url": meeting_url,
                        "status": "left",
                        "reason": "Meeting tab closed",
                    }
                    if final_artifacts:
                        result.update(final_artifacts)
                    return result

                _ensure_microphone_muted(page)

                leave_reason, leave_detail = _meeting_leave_reason(page)
                if leave_reason == "meeting_ended":
                    _log("meeting ended; leaving call")
                    _update_job_meta("leaving", leave_detail)
                    _leave_meeting(page)
                    try:
                        page.close()
                    except Exception:
                        pass
                    final_artifacts = _finalize_meeting_ai(meeting_ai, title)
                    _update_job_meta("left", leave_detail)
                    result = {
                        "title": title,
                        "meeting_url": meeting_url,
                        "status": "left",
                        "reason": "Meeting ended",
                    }
                    if final_artifacts:
                        result.update(final_artifacts)
                    return result

                if leave_reason == "alone":
                    if alone_since is None:
                        alone_since = monotonic()
                        _log("bot appears to be alone; waiting before leaving")
                        _update_job_meta("waiting_to_leave", leave_detail)
                    elif monotonic() - alone_since >= ALONE_GRACE_SECONDS:
                        _log("bot is alone; leaving call")
                        _update_job_meta("leaving", leave_detail)
                        _leave_meeting(page)
                        try:
                            page.close()
                        except Exception:
                            pass
                        final_artifacts = _finalize_meeting_ai(meeting_ai, title)
                        _update_job_meta("left", leave_detail)
                        result = {
                            "title": title,
                            "meeting_url": meeting_url,
                            "status": "left",
                            "reason": "No one else left in the meeting",
                        }
                        if final_artifacts:
                            result.update(final_artifacts)
                        return result
                else:
                    alone_since = None

                contributor_count = _read_contributor_count(page)
                if (
                    contributor_count is not None
                    and contributor_count >= 2
                    and not assistant_messages_sent
                ):
                    _log(f"detected {contributor_count} contributors; sending assistant intro")
                    if _send_assistant_intro_messages(page, title, meeting_ai):
                        assistant_messages_sent = True
                        _set_job_meta_value("assistant_messages_sent", True)
                        _update_job_meta("assistant_messages_sent", str(contributor_count))
                    else:
                        _update_job_meta("assistant_messages_failed", str(contributor_count))

                _maybe_answer_new_questions(page, meeting_ai, contributor_count)

                page.wait_for_timeout(MONITOR_POLL_MS)
        except Exception as error:
            debug = None
            try:
                debug = _write_debug_artifacts(page, title, str(error))
            except Exception:
                pass
            _update_job_meta("monitor_failed", str(error))
            _log(f"monitor failed: {error}")
            final_artifacts = None
            try:
                final_artifacts = _finalize_meeting_ai(meeting_ai, title)
            except Exception:
                pass
            result = {
                "title": title,
                "meeting_url": meeting_url,
                "status": "failed",
                "reason": str(error),
                "debug": debug,
            }
            if final_artifacts:
                result.update(final_artifacts)
            return result


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
        monitor_job_id = None

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
            _ensure_microphone_muted(page)

            _update_job_meta("waiting_prejoin", "0s elapsed")
            wait_state = _wait_for_prejoin_controls(page, timeout_ms=PREJOIN_TIMEOUT_MS)
            if wait_state == "joined":
                _update_job_meta("joined", "already inside meeting")
                keep_page_open = True
                monitor_job_id = _queue_monitor_job(meeting_url, title)
                return {
                    "title": title,
                    "meeting_url": meeting_url,
                    "status": "joined",
                    "reason": "Bot was already inside the meeting",
                    **({"monitor_job_id": monitor_job_id} if monitor_job_id else {}),
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
                monitor_job_id = _queue_monitor_job(meeting_url, title)
                return {
                    "title": title,
                    "meeting_url": meeting_url,
                    "status": "joined",
                    **({"monitor_job_id": monitor_job_id} if monitor_job_id else {}),
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
