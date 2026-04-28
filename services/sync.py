from datetime import datetime
from integrations import google_cal, apple_cal, notion_cal


def create_event_everywhere(title: str, start: datetime, end: datetime) -> dict:
    results = {}
    try:
        results["google"] = google_cal.create_event(title, start, end)
    except Exception as e:
        results["google"] = f"error: {e}"
    try:
        results["apple"] = apple_cal.create_event(title, start, end)
    except Exception as e:
        results["apple"] = f"error: {e}"
    try:
        results["notion"] = notion_cal.create_event(title, start, end)
    except Exception as e:
        results["notion"] = f"error: {e}"
    return results


def list_all_events() -> list[dict]:
    events = []
    for source, fetcher in [
        ("Google", google_cal.list_events),
        ("Apple", apple_cal.list_events),
        ("Notion", notion_cal.list_events),
    ]:
        try:
            for e in fetcher():
                e["source"] = source
                events.append(e)
        except Exception:
            pass
    events.sort(key=lambda e: str(e.get("start") or ""))
    return events
