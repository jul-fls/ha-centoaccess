"""Pure data normalization helpers for CentoAccess entities."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from .const import BASE_URL

JsonObject = dict[str, Any]
Identifier = str | int


def as_object(value: object) -> JsonObject:
    """Return a JSON object or an empty object for another JSON value."""
    if not isinstance(value, dict):
        return {}
    return cast(JsonObject, value)


def object_list(value: object) -> list[JsonObject]:
    """Return only JSON objects contained in a list-like API value."""
    if not isinstance(value, list):
        return []
    items = cast(list[object], value)
    return [cast(JsonObject, item) for item in items if isinstance(item, dict)]


def _identifier(value: object) -> Identifier | None:
    if isinstance(value, (str, int)) and not isinstance(value, bool):
        return value
    return None


def absolute_url(path: str | None) -> str | None:
    """Turn a CentoWeb resource path into a public URL."""
    if path and path.startswith("/"):
        return f"{BASE_URL}{path}"
    return path


def information_summary(item: JsonObject) -> JsonObject:
    """Keep the useful, serializable fields of news, events and practical info."""
    image = as_object(item.get("mainImage"))
    return {
        "id": item.get("id"),
        "title": item.get("title"),
        "subtitle": item.get("subtitle"),
        "content": item.get("content"),
        "description": item.get("description"),
        "published_at": item.get("publishedAt"),
        "created_at": item.get("createdAt"),
        "updated_at": item.get("updatedAt"),
        "enabled": item.get("enabled"),
        "category": item.get("category") or item.get("usefulInfoCategory"),
        "date_start": item.get("dateStart"),
        "date_end": item.get("dateEnd"),
        "time_start": item.get("timeStart"),
        "time_end": item.get("timeEnd"),
        "url": item.get("url"),
        "email": item.get("email"),
        "phone": item.get("phone"),
        "address": item.get("address"),
        "latitude": item.get("latitude"),
        "longitude": item.get("longitude"),
        "image_url": absolute_url(
            path if isinstance((path := image.get("path")), str) else None
        ),
        "files": object_list(item.get("files")),
        "links": object_list(item.get("links")),
    }


def _element_summary(element: JsonObject) -> JsonObject:
    return {
        "id": element.get("id"),
        "type": element.get("type"),
        "content": element.get("content"),
        "image_url": absolute_url(
            path if isinstance((path := element.get("path")), str) else None
        ),
        "video_mp4_url": absolute_url(
            path if isinstance((path := element.get("mp4Path")), str) else None
        ),
        "video_webm_url": absolute_url(
            path if isinstance((path := element.get("webmPath")), str) else None
        ),
        "position": element.get("position"),
        "duration": element.get("totalTime"),
    }


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def publication_datetime(item: JsonObject) -> datetime | None:
    """Return the best publication timestamp exposed for an information item."""
    for key in ("publishedAt", "publicationDate", "dateStart", "createdAt"):
        if parsed := _parse_datetime(item.get(key)):
            return parsed
    return None


def information_status(
    item: JsonObject, now: datetime | None = None
) -> str:
    """Return whether an information item is published or scheduled."""
    now = now or datetime.now().astimezone()
    published_at = publication_datetime(item)
    if published_at is None:
        return "available"
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=now.tzinfo)
    return "scheduled" if published_at > now else "published"


def _timeslot_is_current(slot: JsonObject, now: datetime) -> bool:
    start = _parse_datetime(slot.get("dateStart"))
    end = _parse_datetime(slot.get("dateEnd"))
    return (start is None or start.date() <= now.date()) and (
        end is None or now.date() <= end.date()
    )


def slide_status(slide: JsonObject, now: datetime | None = None) -> str:
    """Return the publication status of a normalized panel slide."""
    now = now or datetime.now().astimezone()
    timeslots = object_list(slide.get("timeslots"))
    if not timeslots:
        return "active"
    if any(
        _timeslot_is_current(
            {
                "dateStart": slot.get("date_start"),
                "dateEnd": slot.get("date_end"),
            },
            now,
        )
        for slot in timeslots
    ):
        return "active"
    starts = [
        parsed
        for slot in timeslots
        if (parsed := _parse_datetime(slot.get("date_start"))) is not None
    ]
    ends = [
        parsed
        for slot in timeslots
        if (parsed := _parse_datetime(slot.get("date_end"))) is not None
    ]
    if starts and all(start.date() > now.date() for start in starts):
        return "scheduled"
    if ends and all(end.date() < now.date() for end in ends):
        return "expired"
    return "inactive"


def panel_slides(
    panel: JsonObject, now: datetime | None = None
) -> list[JsonObject]:
    """Build unique slides with frames, media and publication windows."""
    now = now or datetime.now().astimezone()
    elements = {
        identifier: item
        for item in object_list(panel.get("elements"))
        if (identifier := _identifier(item.get("id"))) is not None
    }
    frames = {
        identifier: item
        for item in object_list(panel.get("frames"))
        if (identifier := _identifier(item.get("id"))) is not None
    }
    versions = {
        identifier: item
        for item in object_list(panel.get("versioned_messages"))
        if (identifier := _identifier(item.get("id"))) is not None
    }
    timeslots = object_list(panel.get("timeslots"))
    message_playlists = {
        identifier: item
        for item in object_list(panel.get("message_playlists"))
        if item.get("enabled")
        and (identifier := _identifier(item.get("id"))) is not None
    }

    slides: list[JsonObject] = []
    seen_message_ids: set[Identifier] = set()
    for message in object_list(panel.get("messages")):
        message_id = _identifier(message.get("id"))
        if message_id in seen_message_ids:
            continue
        if message_id is not None:
            seen_message_ids.add(message_id)
        playlist_ids = [
            identifier
            for item in object_list(message.get("MessagePlaylists"))
            if (identifier := _identifier(item.get("id"))) in message_playlists
        ]
        if not playlist_ids:
            continue

        version_id = _identifier(as_object(message.get("currentVersion")).get("id"))
        version = versions.get(version_id, {}) if version_id is not None else {}
        slide_frames: list[JsonObject] = []
        for frame_ref in object_list(version.get("Frames")):
            frame_id = _identifier(frame_ref.get("id"))
            frame = frames.get(frame_id, {}) if frame_id is not None else {}
            slide_frames.append(
                {
                    "id": frame.get("id"),
                    "position": frame.get("position"),
                    "duration": frame.get("timeTotalFrame"),
                    "background_color": frame.get("backgroundColor"),
                    "elements": [
                        _element_summary(elements[element_id])
                        for element_ref in object_list(frame.get("Elements"))
                        if (element_id := _identifier(element_ref.get("id")))
                        in elements
                    ],
                }
            )
        related_timeslots = [
            slot
            for slot in timeslots
            if _identifier(as_object(slot.get("MessagePlaylist")).get("id"))
            in playlist_ids
        ]
        slide: JsonObject = {
            "id": message_id,
            "name": message.get("name"),
            "active": not related_timeslots
            or any(_timeslot_is_current(slot, now) for slot in related_timeslots),
            "frames": slide_frames,
            "timeslots": [
                {
                    "date_start": slot.get("dateStart"),
                    "date_end": slot.get("dateEnd"),
                    "time_start": slot.get("timeStart"),
                    "time_end": slot.get("timeEnd"),
                    "days": [
                        day
                        for day in cast(list[object], value)
                        if isinstance(day, (str, int))
                    ]
                    if isinstance((value := slot.get("enableDays")), list)
                    else [],
                    "type": slot.get("type"),
                }
                for slot in related_timeslots
            ],
        }
        slide["status"] = slide_status(slide, now)
        slides.append(slide)
    return slides
