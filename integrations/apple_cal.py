from datetime import datetime, timedelta
import uuid

try:
    import caldav
    _CALDAV_AVAILABLE = True
except ImportError:
    _CALDAV_AVAILABLE = False

from config import ICLOUD_USERNAME, ICLOUD_PASSWORD

ICLOUD_URL = "https://caldav.icloud.com"


def _get_calendar():
    if not _CALDAV_AVAILABLE:
        raise RuntimeError("caldav не установлен")
    client = caldav.DAVClient(
        url=ICLOUD_URL,
        username=ICLOUD_USERNAME,
        password=ICLOUD_PASSWORD
    )
    principal = client.principal()
    cals = list(principal.calendars())
    return cals[0] if cals else None


def create_event(title: str, start: datetime, end: datetime) -> str:
    cal = _get_calendar()
    if cal is None:
        raise RuntimeError("No iCloud calendars found")
    uid = str(uuid.uuid4())
    fmt = "%Y%m%dT%H%M%S"
    ical = (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "BEGIN:VEVENT\r\n"
        f"UID:{uid}\r\n"
        f"SUMMARY:{title}\r\n"
        f"DTSTART:{start.strftime(fmt)}\r\n"
        f"DTEND:{end.strftime(fmt)}\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )
    result = cal.add_event(ical)
    return str(result.url)


def list_events(days_ahead: int = 7) -> list[dict]:
    try:
        cal = _get_calendar()
        if cal is None:
            return []
        now = datetime.utcnow()
        events = cal.date_search(
            start=now,
            end=now + timedelta(days=days_ahead),
            expand=True
        )
        result = []
        for e in events:
            try:
                vevent = e.vobject_instance.vevent
                result.append({
                    "title": str(vevent.summary.value),
                    "start": vevent.dtstart.value,
                    "end": vevent.dtend.value,
                })
            except Exception:
                pass
        return result
    except Exception:
        return []
