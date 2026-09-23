"""Calendar platform for CentoAccess."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any, cast

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)
from homeassistant.util import dt as dt_util

from . import CentoAccessConfigEntry
from .api import CommuneData
from .entity import device_info
from .models import (
    JsonObject,
    absolute_url,
    as_object,
    object_list,
    panel_slides,
    publication_datetime,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CentoAccessConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the CentoAccess calendar."""
    async_add_entities([CentoAccessCalendar(entry)])


class CentoAccessCalendar(
    CoordinatorEntity[DataUpdateCoordinator[CommuneData]], CalendarEntity
):
    """Calendar containing agenda, news publications and display slides."""

    _attr_has_entity_name = True
    _attr_translation_key = "agenda"
    _attr_icon = "mdi:calendar-month-outline"

    def __init__(self, entry: CentoAccessConfigEntry) -> None:
        """Initialize the calendar."""
        super().__init__(entry.runtime_data.coordinator)
        self._attr_unique_id = f"{entry.entry_id}_calendar"
        self._attr_device_info = device_info(entry, self.coordinator.data)

    @property
    def event(self) -> CalendarEvent | None:
        """Return the current or next event from every published content type."""
        now = dt_util.now()
        events = _calendar_events(self.coordinator.data, now.date())
        return next(
            (event for event in events if _as_datetime(event.end) > now), None
        )

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        """Return agenda, news and slides in the requested interval."""
        events = _calendar_events(self.coordinator.data, dt_util.now().date())
        return [
            event
            for event in events
            if _as_datetime(event.start) < end_date
            and _as_datetime(event.end) > start_date
        ]


def _calendar_events(data: CommuneData, today: date) -> list[CalendarEvent]:
    events = [
        event for item in data.events if (event := _agenda_event(item)) is not None
    ]
    events.extend(
        event for item in data.news if (event := _news_event(item)) is not None
    )
    for slide in panel_slides(data.panel_data):
        events.extend(_slide_events(slide, today, data.panel_url))
    return sorted(events, key=lambda event: _as_datetime(event.start))


def _agenda_event(item: JsonObject) -> CalendarEvent | None:
    start_date = _parse_date(item.get("dateStart") or item.get("startDate"))
    if start_date is None:
        return None
    end_date = _parse_date(item.get("dateEnd") or item.get("endDate")) or start_date
    summary = str(item.get("title") or item.get("name") or "CentoAccess")
    description = str(item.get("description") or item.get("content") or "")
    location = _location(item)

    start_time = _parse_time(item.get("timeStart") or item.get("startTime"))
    end_time = _parse_time(item.get("timeEnd") or item.get("endTime"))
    return _dated_event(
        summary,
        description,
        location,
        start_date,
        end_date,
        start_time,
        end_time,
    )


def _news_event(item: JsonObject) -> CalendarEvent | None:
    published_at = publication_datetime(item)
    if published_at is None:
        return None
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
    title = str(item.get("title") or item.get("name") or "Actualité")
    return CalendarEvent(
        summary=f"Actualité - {title}",
        start=published_at,
        end=published_at + timedelta(hours=1),
        description=str(item.get("content") or item.get("description") or ""),
        location=_location(item),
    )


def _slide_events(
    slide: JsonObject, today: date, panel_url: str | None
) -> list[CalendarEvent]:
    title = str(slide.get("name") or f"Diapositive {slide.get('id', '')}")
    description = _slide_description(slide)
    timeslots = object_list(slide.get("timeslots"))
    if not timeslots:
        return [
            CalendarEvent(
                summary=f"Diapositive - {title}",
                start=today,
                end=today + timedelta(days=1),
                description=description,
                location=absolute_url(panel_url),
            )
        ]

    events: list[CalendarEvent] = []
    for slot in timeslots:
        start_date = _parse_date(slot.get("date_start")) or today
        end_date = _parse_date(slot.get("date_end")) or start_date
        events.append(
            _dated_event(
                f"Diapositive - {title}",
                description,
                absolute_url(panel_url),
                start_date,
                end_date,
                _parse_time(slot.get("time_start")),
                _parse_time(slot.get("time_end")),
            )
        )
    return events


def _dated_event(
    summary: str,
    description: str,
    location: str | None,
    start_date: date,
    end_date: date,
    start_time: time | None,
    end_time: time | None,
) -> CalendarEvent:
    if start_time is None and end_time is None:
        return CalendarEvent(
            summary=summary,
            start=start_date,
            end=end_date + timedelta(days=1),
            description=description,
            location=location,
        )
    start = datetime.combine(
        start_date, start_time or time.min, dt_util.DEFAULT_TIME_ZONE
    )
    end = datetime.combine(
        end_date, end_time or time.max, dt_util.DEFAULT_TIME_ZONE
    )
    if end <= start:
        end += timedelta(days=1)
    return CalendarEvent(
        summary=summary,
        start=start,
        end=end,
        description=description,
        location=location,
    )


def _slide_description(slide: JsonObject) -> str:
    contents: list[str] = []
    for frame in object_list(slide.get("frames")):
        for element in object_list(frame.get("elements")):
            if content := element.get("content"):
                contents.append(str(content))
    return "\n\n".join(contents)


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    parsed = dt_util.parse_datetime(str(value))
    if parsed is not None:
        return parsed.date()
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _parse_time(value: Any) -> time | None:
    if not value:
        return None
    try:
        return time.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        parsed = dt_util.parse_datetime(str(value))
        return parsed.timetz() if parsed else None


def _location(item: JsonObject) -> str | None:
    value = item.get("location") or item.get("address") or item.get("place")
    if isinstance(value, dict):
        return ", ".join(
            str(part) for part in as_object(cast(object, value)).values() if part
        )
    return str(value) if value else None


def _as_datetime(value: date | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.combine(value, time.min, dt_util.DEFAULT_TIME_ZONE)
