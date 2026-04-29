import json
import os
import re
from datetime import datetime, timezone
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/calendar"]
_creds_cache: Credentials | None = None


def _get_service():
    global _creds_cache
    if _creds_cache and _creds_cache.valid:
        return build("calendar", "v3", credentials=_creds_cache)

    token_data = _load_token_data()
    creds = Credentials(
        token=token_data.get("token"),
        refresh_token=token_data["refresh_token"],
        token_uri=token_data["token_uri"],
        client_id=token_data["client_id"],
        client_secret=token_data["client_secret"],
        scopes=token_data["scopes"],
    )
    if not creds.valid:
        creds.refresh(Request())
    _creds_cache = creds
    return build("calendar", "v3", credentials=creds)


def _load_token_data() -> dict:
    # On Render: env var GOOGLE_TOKEN_JSON holds the full token.json content
    raw = os.getenv("GOOGLE_TOKEN_JSON")
    if raw:
        return json.loads(raw)
    # Local dev: read from file
    token_file = os.getenv("GOOGLE_TOKEN_FILE", "token.json")
    with open(token_file) as f:
        return json.load(f)


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
    service = _get_service()
    now = datetime.utcnow().isoformat() + "Z"
    items = (
        service.events()
        .list(calendarId="primary", timeMin=now, maxResults=50, singleEvents=True, orderBy="startTime")
        .execute()
        .get("items", [])
    )
    query_words = _keywords(title)
    scored = [(len(query_words & _keywords(item.get("summary", ""))), item)
              for item in items]
    scored = [(s, i) for s, i in scored if s > 0]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored[:max_results]]


def delete_event(event_id: str) -> None:
    _get_service().events().delete(calendarId="primary", eventId=event_id).execute()


def list_events(max_results: int = 10) -> list[dict]:
    service = _get_service()
    now = datetime.utcnow().isoformat() + "Z"
    return (
        service.events()
        .list(calendarId="primary", timeMin=now, maxResults=max_results, singleEvents=True, orderBy="startTime")
        .execute()
        .get("items", [])
    )


_STOPWORDS = {"в", "во", "на", "с", "со", "по", "за", "из", "у", "о", "к", "а", "и", "не"}


def _keywords(text: str) -> set:
    words = re.findall(r"[а-яёa-z]+", text.lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 1}
