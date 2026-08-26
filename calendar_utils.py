import asyncio
import json
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from google.oauth2 import service_account
from googleapiclient.discovery import build


GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
GOOGLE_CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID")
TIMEZONE = ZoneInfo("Europe/Moscow")


def _load_busy_sync(date_str: str) -> list[dict]:
if not GOOGLE_SERVICE_ACCOUNT_JSON or not GOOGLE_CALENDAR_ID:
return []

info = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)

credentials = service_account.Credentials.from_service_account_info(
info,
scopes=["https://www.googleapis.com/auth/calendar.readonly"],
)

service = build(
"calendar",
"v3",
credentials=credentials,
cache_discovery=False,
)

day = datetime.strptime(date_str, "%d.%m.%Y").date()

start = datetime.combine(
day,
datetime.min.time(),
tzinfo=TIMEZONE,
)
end = start + timedelta(days=1)

events = (
service.events()
.list(
calendarId=GOOGLE_CALENDAR_ID,
timeMin=start.isoformat(),
timeMax=end.isoformat(),
singleEvents=True,
orderBy="startTime",
)
.execute()
.get("items", [])
)

occupied = []

for event in events:
start_value = event.get("start", {}).get("dateTime")
end_value = event.get("end", {}).get("dateTime")

if not start_value or not end_value:
continue

event_start = datetime.fromisoformat(
start_value.replace("Z", "+00:00")
).astimezone(TIMEZONE)

event_end = datetime.fromisoformat(
end_value.replace("Z", "+00:00")
).astimezone(TIMEZONE)

duration_min = max(
1,
int((event_end - event_start).total_seconds() / 60),
)

occupied.append(
{
"time": event_start.strftime("%H:%M"),
"duration_min": duration_min,
}
)

return occupied


async def get_google_busy(date_str: str) -> list[dict]:
return await asyncio.to_thread(_load_busy_sync, date_str)

