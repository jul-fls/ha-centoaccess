"""Pure data normalization helpers for CentoAccess entities."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .const import BASE_URL


def absolute_url(path: str | None) -> str | None:
    """Turn a CentoWeb resource path into a public URL."""
    if path and path.startswith("/"):
        return f"{BASE_URL}{path}"
    return path


def information_summary(item: dict[str, Any]) -> dict[str, Any]:
    """Keep the useful, serializable fields of news, events and practical info."""
    image = item.get("mainImage") or {}
    return {
        "id": item.get("id"),
        "title": item.get("title"),
        "content": item.get("content"),
        "published_at": item.get("publishedAt"),
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
        "image_url": absolute_url(image.get("path")),
        "files": item.get("files") or [],
        "links": item.get("links") or [],
    }


def _element_summary(element: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": element.get("id"),
        "type": element.get("type"),
        "content": element.get("content"),
        "image_url": absolute_url(element.get("path")),
        "video_mp4_url": absolute_url(element.get("mp4Path")),
        "video_webm_url": absolute_url(element.get("webmPath")),
        "position": element.get("position"),
        "duration": element.get("totalTime"),
    }


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _timeslot_is_current(slot: dict[str, Any], now: datetime) -> bool:
    start = _parse_datetime(slot.get("dateStart"))
    end = _parse_datetime(slot.get("dateEnd"))
    return (start is None or start.date() <= now.date()) and (
        end is None or now.date() <= end.date()
    )


def panel_slides(
    panel: dict[str, Any], now: datetime | None = None
) -> list[dict[str, Any]]:
    """Build unique slides with frames, media and publication windows."""
    now = now or datetime.now().astimezone()
    elements = {item.get("id"): item for item in panel.get("elements") or []}
    frames = {item.get("id"): item for item in panel.get("frames") or []}
    versions = {
        item.get("id"): item for item in panel.get("versioned_messages") or []
    }
    timeslots = panel.get("timeslots") or []
    message_playlists = {
        item.get("id"): item
        for item in panel.get("message_playlists") or []
        if item.get("enabled")
    }

    slides = []
    seen_message_ids: set[int] = set()
    for message in panel.get("messages") or []:
        message_id = message.get("id")
        if message_id in seen_message_ids:
            continue
        if message_id is not None:
            seen_message_ids.add(message_id)
        playlist_ids = [
            item.get("id")
            for item in message.get("MessagePlaylists") or []
            if item.get("id") in message_playlists
        ]
        if not playlist_ids:
            continue

        version_id = (message.get("currentVersion") or {}).get("id")
        version = versions.get(version_id) or {}
        slide_frames = []
        for frame_ref in version.get("Frames") or []:
            frame = frames.get(frame_ref.get("id")) or {}
            slide_frames.append(
                {
                    "id": frame.get("id"),
                    "position": frame.get("position"),
                    "duration": frame.get("timeTotalFrame"),
                    "background_color": frame.get("backgroundColor"),
                    "elements": [
                        _element_summary(elements[element_ref.get("id")])
                        for element_ref in frame.get("Elements") or []
                        if element_ref.get("id") in elements
                    ],
                }
            )
        related_timeslots = [
            slot
            for slot in timeslots
            if (slot.get("MessagePlaylist") or {}).get("id") in playlist_ids
        ]
        slides.append(
            {
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
                        "days": slot.get("enableDays") or [],
                        "type": slot.get("type"),
                    }
                    for slot in related_timeslots
                ],
            }
        )
    return slides
