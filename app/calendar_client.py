import datetime
import os.path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]


def _load_credentials():
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)

        with open("token.json", "w") as token:
            token.write(creds.to_json())

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
