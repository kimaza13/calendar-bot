from datetime import datetime
from notion_client import Client
from config import NOTION_TOKEN, NOTION_DATABASE_ID


def _get_client() -> Client:
    return Client(auth=NOTION_TOKEN)


def create_event(title: str, start: datetime, end: datetime) -> str:
    client = _get_client()
    page = client.pages.create(
        parent={"database_id": NOTION_DATABASE_ID},
        properties={
            "Name": {"title": [{"text": {"content": title}}]},
            "Date": {
                "date": {
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                }
            },
        },
    )
    return page["id"]


def list_events(max_results: int = 10) -> list[dict]:
    client = _get_client()
    now = datetime.utcnow().isoformat()
    response = client.databases.query(
        database_id=NOTION_DATABASE_ID,
        filter={"property": "Date", "date": {"on_or_after": now}},
        sorts=[{"property": "Date", "direction": "ascending"}],
        page_size=max_results,
    )
    events = []
    for page in response["results"]:
        props = page["properties"]
        title = props.get("Name", {}).get("title", [{}])[0].get("text", {}).get("content", "")
        date = props.get("Date", {}).get("date", {})
        events.append({"title": title, "start": date.get("start"), "end": date.get("end")})
    return events
