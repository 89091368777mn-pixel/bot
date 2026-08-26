import asyncio
import json
import os
import re
from datetime import datetime, timedelta
from urllib.error import URLError
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


TIMEZONE = ZoneInfo(os.getenv("CALENDAR_TIMEZONE", "Europe/Moscow"))
CALENDAR_SYNC_TIMEOUT = float(os.getenv("CALENDAR_SYNC_TIMEOUT", "8"))
SLOT_STEP_MINUTES = 30

# Backward-compatible single Google Calendar config.
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
GOOGLE_CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID")

# Separate calendars for the no-overlap rule:
# 1) Uni-Q resource calendar: couch + shower.
# 2) Massage Future / DIKIDI calendar.
UNIQ_GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("UNIQ_GOOGLE_SERVICE_ACCOUNT_JSON") or GOOGLE_SERVICE_ACCOUNT_JSON
UNIQ_GOOGLE_CALENDAR_ID = os.getenv("UNIQ_GOOGLE_CALENDAR_ID")
DIKIDI_GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("DIKIDI_GOOGLE_SERVICE_ACCOUNT_JSON") or GOOGLE_SERVICE_ACCOUNT_JSON
DIKIDI_GOOGLE_CALENDAR_ID = os.getenv("DIKIDI_GOOGLE_CALENDAR_ID") or GOOGLE_CALENDAR_ID

# Optional JSON feeds. URL may include {date} as DD.MM.YYYY or {date_iso} as YYYY-MM-DD.
UNIQ_CALENDAR_URL = os.getenv("UNIQ_CALENDAR_URL")
UNIQ_CALENDAR_TOKEN = os.getenv("UNIQ_CALENDAR_TOKEN")
DIKIDI_CALENDAR_URL = os.getenv("DIKIDI_CALENDAR_URL")
DIKIDI_CALENDAR_TOKEN = os.getenv("DIKIDI_CALENDAR_TOKEN")

UNIQ_REQUIRED_RESOURCES = tuple(
    item.strip().lower()
    for item in os.getenv("UNIQ_REQUIRED_RESOURCES", "кушетка,душ").split(",")
    if item.strip()
)


def date_to_iso(value: str) -> str:
    return datetime.strptime(value, "%d.%m.%Y").strftime("%Y-%m-%d")


def _calendar_url_with_date(url: str, date: str) -> str:
    date_iso = date_to_iso(date)
    if "{date}" in url or "{date_iso}" in url:
        return url.replace("{date}", date).replace("{date_iso}", date_iso)
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.setdefault("date", date)
    query.setdefault("date_iso", date_iso)
    return urlunparse(parsed._replace(query=urlencode(query)))


def _fetch_calendar_json(url: str, token: str | None, date: str) -> object:
    request_url = _calendar_url_with_date(url, date)
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(request_url, headers=headers)
    with urlopen(request, timeout=CALENDAR_SYNC_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def _extract_calendar_events(payload: object) -> list[dict]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("items", "events", "records", "appointments", "bookings"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    for key in ("data", "result"):
        nested = _extract_calendar_events(payload.get(key))
        if nested:
            return nested
    return []


def _parse_calendar_datetime(value: object, fallback_date: str | None = None) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if re.match(r"^\d{1,2}:\d{2}$", text) and fallback_date:
        return datetime.strptime(f"{fallback_date} {text}", "%d.%m.%Y %H:%M")
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo:
            parsed = parsed.astimezone(TIMEZONE).replace(tzinfo=None)
        return parsed
    except ValueError:
        pass
    for fmt in ("%d.%m.%Y %H:%M", "%Y-%m-%d %H:%M", "%d.%m.%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _event_resource(event: dict) -> str:
    values = [
        event.get("resource"),
        event.get("resource_name"),
        event.get("resourceName"),
        event.get("resource_title"),
        event.get("resourceTitle"),
        event.get("room"),
        event.get("place"),
        event.get("location"),
        event.get("summary"),
        event.get("title"),
    ]
    return " ".join(str(value).lower() for value in values if value)


def _event_blocks_required_resource(event: dict) -> bool:
    if not UNIQ_REQUIRED_RESOURCES:
        return True
    resource = _event_resource(event)
    if not resource:
        # If the feed is already scoped to Uni-Q resources, empty resource still blocks.
        return True
    return any(required in resource for required in UNIQ_REQUIRED_RESOURCES)


def _duration_from_event(event: dict, default: int) -> int:
    for key in ("duration_min", "duration", "duration_minutes", "length"):
        value = event.get(key)
        if value is None:
            continue
        try:
            return max(int(value), SLOT_STEP_MINUTES)
        except (TypeError, ValueError):
            continue
    return default


def _busy_from_event(event: dict, date: str, default_duration: int) -> dict | None:
    event_date = str(event.get("date") or event.get("day") or date)
    if re.match(r"^\d{4}-\d{2}-\d{2}$", event_date):
        event_date = datetime.strptime(event_date, "%Y-%m-%d").strftime("%d.%m.%Y")

    start_value = (
        event.get("start")
        or event.get("start_at")
        or event.get("started_at")
        or event.get("date_start")
        or event.get("datetime_from")
        or event.get("from")
        or event.get("time")
        or event.get("start_time")
    )
    if isinstance(start_value, dict):
        start_value = start_value.get("dateTime") or start_value.get("date")
    start = _parse_calendar_datetime(start_value, event_date)
    if not start:
        return None

    end_value = (
        event.get("end")
        or event.get("end_at")
        or event.get("finished_at")
        or event.get("date_end")
        or event.get("datetime_to")
        or event.get("to")
        or event.get("end_time")
    )
    if isinstance(end_value, dict):
        end_value = end_value.get("dateTime") or end_value.get("date")
    end = _parse_calendar_datetime(end_value, event_date)
    duration = _duration_from_event(event, default_duration)
    if end and end > start:
        duration = max(int((end - start).total_seconds() / 60), SLOT_STEP_MINUTES)
    return {"time": start.strftime("%H:%M"), "duration_min": duration}


def _load_google_busy_sync(
    date_str: str,
    service_account_json: str | None,
    calendar_id: str | None,
) -> list[dict]:
    if not service_account_json or not calendar_id:
        return []

    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    info = json.loads(service_account_json)
    credentials = service_account.Credentials.from_service_account_info(
        info,
        scopes=["https://www.googleapis.com/auth/calendar.readonly"],
    )
    service = build("calendar", "v3", credentials=credentials, cache_discovery=False)
    day = datetime.strptime(date_str, "%d.%m.%Y").date()
    start = datetime.combine(day, datetime.min.time(), tzinfo=TIMEZONE)
    end = start + timedelta(days=1)
    events = (
        service.events()
        .list(
            calendarId=calendar_id,
            timeMin=start.isoformat(),
            timeMax=end.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
        .get("items", [])
    )
    busy: list[dict] = []
    for event in events:
        item = _busy_from_event(event, date_str, SLOT_STEP_MINUTES)
        if item:
            busy.append(item)
    return busy


async def get_google_busy(date_str: str) -> list[dict]:
    return await asyncio.to_thread(_load_google_busy_sync, date_str, GOOGLE_SERVICE_ACCOUNT_JSON, GOOGLE_CALENDAR_ID)


async def _busy_from_google_calendar(
    date: str,
    service_account_json: str | None,
    calendar_id: str | None,
    resource_filter: bool = False,
) -> list[dict]:
    try:
        busy = await asyncio.to_thread(_load_google_busy_sync, date, service_account_json, calendar_id)
    except Exception:
        return []
    if not resource_filter:
        return busy
    # Google busy entries already lost resource metadata after normalization.
    # Use separate/scoped calendars for Uni-Q resources, or JSON feed if resource filtering is required.
    return busy


async def _busy_from_json_feed(
    name: str,
    url: str | None,
    token: str | None,
    date: str,
    default_duration: int,
    resource_filter: bool = False,
) -> list[dict]:
    if not url:
        return []
    try:
        payload = await asyncio.to_thread(_fetch_calendar_json, url, token, date)
    except (OSError, URLError, TimeoutError, json.JSONDecodeError):
        return []
    busy: list[dict] = []
    for event in _extract_calendar_events(payload):
        if resource_filter and not _event_blocks_required_resource(event):
            continue
        item = _busy_from_event(event, date, default_duration)
        if item:
            busy.append(item)
    return busy


async def get_external_busy(date: str, duration_min: int) -> list[dict]:
    dikidi_google, dikidi_feed, uniq_google, uniq_feed = await asyncio.gather(
        _busy_from_google_calendar(date, DIKIDI_GOOGLE_SERVICE_ACCOUNT_JSON, DIKIDI_GOOGLE_CALENDAR_ID),
        _busy_from_json_feed("dikidi", DIKIDI_CALENDAR_URL, DIKIDI_CALENDAR_TOKEN, date, duration_min),
        _busy_from_google_calendar(date, UNIQ_GOOGLE_SERVICE_ACCOUNT_JSON, UNIQ_GOOGLE_CALENDAR_ID, resource_filter=True),
        _busy_from_json_feed("uniq", UNIQ_CALENDAR_URL, UNIQ_CALENDAR_TOKEN, date, duration_min, resource_filter=True),
    )
    return dikidi_google + dikidi_feed + uniq_google + uniq_feed


def calendars_configured() -> bool:
    has_dikidi = bool(DIKIDI_GOOGLE_CALENDAR_ID or DIKIDI_CALENDAR_URL)
    has_uniq = bool(UNIQ_GOOGLE_CALENDAR_ID or UNIQ_CALENDAR_URL)
    return has_dikidi and has_uniq


async def calendar_sync_status_text(date: str | None = None) -> str:
    target_date = date or datetime.now(TIMEZONE).strftime("%d.%m.%Y")
    busy = await get_external_busy(target_date, 60)
    return (
        "Синхронизация календарей:\n\n"
        f"Uni-Q Google Calendar: {'задан' if UNIQ_GOOGLE_CALENDAR_ID else 'не задан'}\n"
        f"Uni-Q JSON URL: {'задан' if UNIQ_CALENDAR_URL else 'не задан'}\n"
        f"Uni-Q resources: {', '.join(UNIQ_REQUIRED_RESOURCES) if UNIQ_REQUIRED_RESOURCES else 'все'}\n"
        f"Мой DIKIDI Google Calendar: {'задан' if DIKIDI_GOOGLE_CALENDAR_ID else 'не задан'}\n"
        f"Мой DIKIDI JSON URL: {'задан' if DIKIDI_CALENDAR_URL else 'не задан'}\n"
        f"Дата проверки: {target_date}\n"
        f"Внешних занятых интервалов найдено: {len(busy)}\n\n"
        "Для режима без наложений нужны два источника: календарь Uni-Q по кушетке/душу "
        "и календарь Массаж будущего/DIKIDI."
    )
