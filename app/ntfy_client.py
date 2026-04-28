import os
import re
from urllib import request


DEFAULT_TOPIC = "ai-personal-assistant"
DEFAULT_SERVER = "https://ntfy.sh"
MAX_BODY_CHARS = 3500


def _chunk_text(text: str, chunk_size: int = MAX_BODY_CHARS):
    text = text.strip()
    if not text:
        return []

    return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]


def _extract_action_items(summary: str) -> list[str]:
    lines = [line.rstrip() for line in summary.splitlines()]
    action_items: list[str] = []
    collecting = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if collecting and action_items:
                break
            continue

        lower = stripped.lower()
        if re.fullmatch(r"(action items?|next steps?)\s*:?", lower):
            collecting = True
            continue

        if collecting:
            if re.match(r"^(summary|decisions?|risks?|concerns?)\s*:?\s*$", lower):
                break

            item = re.sub(r"^[-*•\d.)\s]+", "", stripped).strip()
            if item:
                action_items.append(item)
                if len(action_items) >= 5:
                    break

    return action_items


def _format_summary_markdown(title: str, summary: str) -> str:
    action_items = _extract_action_items(summary)
    parts = [
        f"# Meeting summary",
        f"**Meeting:** {title}",
        "",
        "## Summary",
        summary.strip(),
    ]

    if action_items:
        parts.extend(
            [
                "",
                "## Action items",
                *[f"- {item}" for item in action_items[:5]],
            ]
        )

    return "\n".join(parts).strip()


def _format_transcript_markdown(title: str, chunk: str, index: int, total: int) -> str:
    return "\n".join(
        [
            f"# Transcript follow-up {index}/{total}",
            f"**Meeting:** {title}",
            "",
            "```",
            chunk.strip(),
            "```",
        ]
    ).strip()


def _post_message(server: str, topic: str, title: str, body: str):
    url = f"{server.rstrip('/')}/{topic}"
    payload = body.encode("utf-8")
    req = request.Request(url, data=payload, method="POST")
    req.add_header("Content-Type", "text/markdown; charset=utf-8")
    req.add_header("Title", title)
    req.add_header("Markdown", "yes")
    with request.urlopen(req, timeout=30) as response:
        response.read()


def send_meeting_report(title: str, transcript: str, summary: str):
    topic = os.getenv("NTFY_TOPIC", DEFAULT_TOPIC).strip() or DEFAULT_TOPIC
    server = os.getenv("NTFY_SERVER", DEFAULT_SERVER).strip() or DEFAULT_SERVER

    messages_sent = 0

    summary_text = summary.strip()
    if summary_text:
        _post_message(
            server,
            topic,
            f"Meeting summary: {title}",
            _format_summary_markdown(title, summary_text),
        )
        messages_sent += 1

    transcript_text = transcript.strip()
    if transcript_text:
        chunks = _chunk_text(transcript_text)
        total = len(chunks)
        for index, chunk in enumerate(chunks, start=1):
            _post_message(
                server,
                topic,
                f"Meeting transcript: {title} ({index}/{total})",
                _format_transcript_markdown(title, chunk, index, total),
            )
            messages_sent += 1

    return {
        "sent": messages_sent > 0,
        "topic": topic,
        "server": server,
        "messages_sent": messages_sent,
    }
