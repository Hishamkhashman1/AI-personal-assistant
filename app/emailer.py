import os
import smtplib
from email.message import EmailMessage
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def send_meeting_report(
    title: str,
    transcript: str,
    summary: str,
    transcript_path: str | None = None,
):
    recipient = os.getenv("MEETING_REPORT_EMAIL")
    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = _env_int("SMTP_PORT", 587)
    smtp_username = os.getenv("SMTP_USERNAME")
    smtp_password = os.getenv("SMTP_PASSWORD")
    smtp_from = os.getenv("SMTP_FROM_EMAIL") or smtp_username
    use_ssl = _env_bool("SMTP_USE_SSL", False)
    use_tls = _env_bool("SMTP_USE_TLS", True)

    if not recipient or not smtp_host:
        return {
            "sent": False,
            "reason": "Email delivery is not configured",
        }

    if not smtp_from:
        smtp_from = recipient

    message = EmailMessage()
    message["Subject"] = f"Meeting report: {title}"
    message["From"] = smtp_from
    message["To"] = recipient
    message.set_content(
        "\n\n".join(
            [
                f"Meeting: {title}",
                "Summary:",
                summary.strip(),
                "Transcript:",
                transcript.strip(),
            ]
        )
    )

    if transcript_path:
        try:
            path = Path(transcript_path)
            if path.is_file():
                message.add_attachment(
                    path.read_bytes(),
                    maintype="text",
                    subtype="plain",
                    filename=path.name,
                )
        except Exception:
            pass

    if use_ssl:
        smtp = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30)
    else:
        smtp = smtplib.SMTP(smtp_host, smtp_port, timeout=30)

    try:
        smtp.ehlo()
        if use_tls and not use_ssl:
            smtp.starttls()
            smtp.ehlo()
        if smtp_username:
            smtp.login(smtp_username, smtp_password or "")
        smtp.send_message(message)
    finally:
        try:
            smtp.quit()
        except Exception:
            pass

    return {
        "sent": True,
        "recipient": recipient,
    }
