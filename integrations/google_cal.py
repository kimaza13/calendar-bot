from datetime import datetime
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import os

SCOPES = ["https://www.googleapis.com/auth/calendar"]
TOKEN_FILE = "token.json"


def _get_service():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            from config import GOOGLE_CREDENTIALS_JSON
            flow = InstalledAppFlow.from_client_secrets_file(GOOGLE_CREDENTIALS_JSON, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
    return build("calendar", "v3", credentials=creds)


def create_event(title: str, start: datetime, end: datetime) -> str:
    service = _get_service()
    event = {
        "summary": title,
        "start": {"dateTime": start.isoformat(), "timeZone": "UTC"},
        "end": {"dateTime": end.isoformat(), "timeZone": "UTC"},
    }
    result = service.events().insert(calendarId="primary", body=event).execute()
    return result["id"]


def find_events_by_title(title: str, max_results: int = 5) -> list[dict]:
    """Return upcoming events ranked by keyword overlap with title."""
    service = _get_service()
    now = datetime.utcnow().isoformat() + "Z"
    items = (
        service.events()
        .list(calendarId="primary", timeMin=now, maxResults=50, singleEvents=True, orderBy="startTime")
        .execute()
        .get("items", [])
    )
    query_words = _keywords(title)
    scored = []
    for item in items:
        summary = item.get("summary", "")
        score = len(query_words & _keywords(summary))
        if score > 0:
            scored.append((score, item))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored[:max_results]]


_STOPWORDS = {"в", "во", "на", "с", "со", "по", "за", "из", "у", "о", "к", "а", "и", "не"}


def _keywords(text: str) -> set:
    import re
    words = re.findall(r"[а-яёa-z]+", text.lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 1}


def delete_event(event_id: str) -> None:
    service = _get_service()
    service.events().delete(calendarId="primary", eventId=event_id).execute()


def list_events(max_results: int = 10) -> list[dict]:
    service = _get_service()
    now = datetime.utcnow().isoformat() + "Z"
    result = (
        service.events()
        .list(calendarId="primary", timeMin=now, maxResults=max_results, singleEvents=True, orderBy="startTime")
        .execute()
    )
    return result.get("items", [])
