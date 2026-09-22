"""Calendar platform for CentoAccess."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import CentoAccessConfigEntry
from .entity import CentoAccessEntityMixin


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CentoAccessConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the CentoAccess calendar."""
    async_add_entities([CentoAccessCalendar(entry)])


class CentoAccessCalendar(
    CentoAccessEntityMixin, CoordinatorEntity, CalendarEntity
):
    """Calendar containing the commune agenda."""

    _attr_has_entity_name = True
    _attr_translation_key = "agenda"
    _attr_icon = "mdi:calendar-month-outline"

    def __init__(self, entry: CentoAccessConfigEntry) -> None:
        """Initialize the calendar."""
        super().__init__(entry.runtime_data.coordinator)
        self._attr_unique_id = f"{entry.entry_id}_calendar"
        self._set_device_info(entry)

    @property
    def event(self) -> CalendarEvent | None:
        """Return the current or next event."""
        now = dt_util.now()
        events = sorted(
            (event for item in self.coordinator.data.events if (event := _event(item))),
            key=lambda event: _as_datetime(event.start),
        )
        return next(
            (event for event in events if _as_datetime(event.end) > now), None
        )

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        """Return events in the requested interval."""
        events = [
            event
            for item in self.coordinator.data.events
            if (event := _event(item))
            and _as_datetime(event.start) < end_date
            and _as_datetime(event.end) > start_date
        ]
        return sorted(events, key=lambda event: _as_datetime(event.start))


def _event(item: dict[str, Any]) -> CalendarEvent | None:
    start_date = _parse_date(item.get("dateStart") or item.get("startDate"))
    if start_date is None:
        return None
    end_date = _parse_date(item.get("dateEnd") or item.get("endDate")) or start_date
    summary = str(item.get("title") or item.get("name") or "CentoAccess")
    description = str(item.get("description") or item.get("content") or "")
    location = _location(item)

    start_time = _parse_time(item.get("timeStart") or item.get("startTime"))
    end_time = _parse_time(item.get("timeEnd") or item.get("endTime"))
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
    end = datetime.combine(end_date, end_time or time.max, dt_util.DEFAULT_TIME_ZONE)
    if end <= start:
        end += timedelta(days=1)
    return CalendarEvent(
        summary=summary,
        start=start,
        end=end,
        description=description,
        location=location,
    )


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


def _location(item: dict[str, Any]) -> str | None:
    value = item.get("location") or item.get("address") or item.get("place")
    if isinstance(value, dict):
        return ", ".join(str(part) for part in value.values() if part)
    return str(value) if value else None


def _as_datetime(value: date | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.combine(value, time.min, dt_util.DEFAULT_TIME_ZONE)
