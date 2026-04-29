from datetime import datetime, timedelta
try:
    import caldav
    _CALDAV_AVAILABLE = True
except ImportError:
    _CALDAV_AVAILABLE = False

from config import ICLOUD_USERNAME, ICLOUD_PASSWORD

ICLOUD_URL = "https://caldav.icloud.com"


def _get_client():
    if not _CALDAV_AVAILABLE:
        raise RuntimeError("caldav не установлен")
    return caldav.DAVClient(
        url=ICLOUD_URL,
        username=ICLOUD_USERNAME,
        password=ICLOUD_PASSWORD
    )


def _get_calendar():
    client = _get_client()
    principal = client.principal()
    calendars = principal.calendars()
    cal_list = list(calendars)
    return cal_list[0] if cal_list else None


def create_event(title: str, start: datetime, end: datetime) -> str:
    cal = _get_calendar()
    if cal is None:
        raise RuntimeError("No iCloud calendars found")
    event = cal.save_event(
        dtstart=start,
        dtend=end,
        summary=title,
    )
    return str(event.url)


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
