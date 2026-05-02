import datetime
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.settings import BASE_DIR, env

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
CLIENT_SECRETS_FILE = Path(env("GOOGLE_OAUTH_CLIENT_SECRETS", str(BASE_DIR / "credentials.json")))
TOKEN_FILE = Path(env("GOOGLE_OAUTH_TOKEN_FILE", str(BASE_DIR / "token.json")))


def _load_credentials():
    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CLIENT_SECRETS_FILE.exists():
                raise FileNotFoundError(
                    f"Google OAuth client secrets file not found: {CLIENT_SECRETS_FILE}"
                )

            flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRETS_FILE), SCOPES)
            creds = flow.run_local_server(port=0)

        TOKEN_FILE.write_text(creds.to_json())

    return creds


def _extract_meeting_url(event):
    hangout_link = event.get("hangoutLink")
    if hangout_link:
        return hangout_link

    conference_data = event.get("conferenceData") or {}
    for entry_point in conference_data.get("entryPoints", []):
        if entry_point.get("entryPointType") == "video" and entry_point.get("uri"):
            return entry_point["uri"]

    return None


def _format_event(event):
    start = event.get("start", {}).get("dateTime", event.get("start", {}).get("date"))
    return {
        "title": event.get("summary", "Untitled meeting"),
        "start": start,
        "meeting_url": _extract_meeting_url(event),
    }


def get_upcoming_events(max_results=10):
    creds = _load_credentials()

    try:
        service = build("calendar", "v3", credentials=creds)
        now = datetime.datetime.now(tz=datetime.timezone.utc).isoformat()
        events_result = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=now,
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        events = events_result.get("items", [])
        return [_format_event(event) for event in events]
    except HttpError as error:
        print(f"An error occurred: {error}")
        return []


def get_next_event_with_meet_link(max_results=10):
    for event in get_upcoming_events(max_results=max_results):
        if event.get("meeting_url"):
            return event
    return None


def calendar_integration():
    """Backward-compatible wrapper for the next Meet-linked event."""
    return get_next_event_with_meet_link()
