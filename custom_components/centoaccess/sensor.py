"""Static and dynamic sensors for CentoAccess."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, cast

from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from . import CentoAccessConfigEntry
from .api import CommuneData
from .const import DOMAIN
from .entity import device_info
from .models import (
    JsonObject,
    as_object,
    information_status,
    information_summary,
    panel_slides,
    slide_status,
)

KIND_NEWS = "news_item"
KIND_SLIDE = "slide_item"
KIND_USEFUL = "useful_info_item"
DynamicKey = tuple[str, str]


@dataclass(frozen=True, kw_only=True)
class CentoAccessSensorDescription(SensorEntityDescription):
    """Describe a static CentoAccess sensor."""

    value_fn: Callable[[CommuneData], Any]
    attributes_fn: Callable[[CommuneData], Mapping[str, Any]]


SENSORS = (
    CentoAccessSensorDescription(
        key="commune",
        translation_key="commune",
        icon="mdi:city-variant-outline",
        value_fn=lambda data: data.application.get("name", "CentoAccess"),
        attributes_fn=lambda data: {
            "application_id": data.application.get("id"),
            "postal_code": data.application.get("postalCode"),
            "tiles": data.tiles,
            "panel_id": data.panel_id,
        },
    ),
    CentoAccessSensorDescription(
        key="slides",
        translation_key="slides",
        icon="mdi:view-carousel-outline",
        value_fn=lambda data: sum(
            slide["active"] for slide in panel_slides(data.panel_data)
        ),
        attributes_fn=lambda data: {
            "total": len(panel_slides(data.panel_data)),
            "item_ids": [
                slide["id"] for slide in panel_slides(data.panel_data)
            ],
        },
    ),
    CentoAccessSensorDescription(
        key="agenda",
        translation_key="agenda",
        icon="mdi:calendar-month-outline",
        value_fn=lambda data: len(data.events),
        attributes_fn=lambda data: {
            "item_ids": [item.get("id") for item in data.events]
        },
    ),
    CentoAccessSensorDescription(
        key="news",
        translation_key="news",
        icon="mdi:newspaper-variant-outline",
        value_fn=lambda data: len(data.news),
        attributes_fn=lambda data: {
            "item_ids": [item.get("id") for item in data.news]
        },
    ),
    CentoAccessSensorDescription(
        key="useful_info",
        translation_key="useful_info",
        icon="mdi:information-outline",
        value_fn=lambda data: len(data.useful_info),
        attributes_fn=lambda data: {
            "item_ids": [item.get("id") for item in data.useful_info]
        },
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CentoAccessConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up static sensors and synchronize content entities."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        CentoAccessSensor(entry, description) for description in SENSORS
    )

    registry = er.async_get(hass)
    known: set[DynamicKey] = set()
    registered = _registered_dynamic_keys(registry, entry)

    @callback
    def sync_dynamic_entities() -> None:
        desired = _dynamic_keys(coordinator.data)
        for kind, item_id in (known | registered) - desired:
            unique_id = _dynamic_unique_id(entry, kind, item_id)
            entity_id = registry.async_get_entity_id(
                SENSOR_DOMAIN, DOMAIN, unique_id
            )
            if entity_id:
                registry.async_remove(entity_id)
        known.intersection_update(desired)
        registered.clear()

        new_keys = desired - known
        if new_keys:
            async_add_entities(
                CentoAccessContentSensor(entry, kind, item_id)
                for kind, item_id in sorted(new_keys)
            )
            known.update(new_keys)

    sync_dynamic_entities()
    entry.async_on_unload(coordinator.async_add_listener(sync_dynamic_entities))


class CentoAccessSensor(
    CoordinatorEntity[DataUpdateCoordinator[CommuneData]], SensorEntity
):
    """Representation of a static CentoAccess sensor."""

    entity_description: CentoAccessSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        entry: CentoAccessConfigEntry,
        description: CentoAccessSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(entry.runtime_data.coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = device_info(entry, self.coordinator.data)

    @property
    def native_value(self) -> Any:
        """Return the sensor value."""
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> Mapping[str, Any]:
        """Return summary data."""
        return self.entity_description.attributes_fn(self.coordinator.data)


class CentoAccessContentSensor(
    CoordinatorEntity[DataUpdateCoordinator[CommuneData]], SensorEntity
):
    """One dynamically published news item, slide or useful-information item."""

    _attr_has_entity_name = True

    def __init__(
        self, entry: CentoAccessConfigEntry, kind: str, item_id: str
    ) -> None:
        """Initialize a dynamic content sensor."""
        super().__init__(entry.runtime_data.coordinator)
        self.kind = kind
        self.item_id = item_id
        self._attr_unique_id = _dynamic_unique_id(entry, kind, item_id)
        item = self._item()
        self._attr_name = _item_name(kind, item, item_id)
        self._attr_icon = {
            KIND_NEWS: "mdi:newspaper-variant-outline",
            KIND_SLIDE: "mdi:view-carousel-outline",
            KIND_USEFUL: "mdi:information-outline",
        }[kind]
        self._attr_device_info = device_info(entry, self.coordinator.data)

    def _item(self) -> dict[str, Any] | None:
        return _find_dynamic_item(self.coordinator.data, self.kind, self.item_id)

    @property
    def available(self) -> bool:
        """Return whether the item is still present in the latest response."""
        return super().available and self._item() is not None

    @property
    def native_value(self) -> str | None:
        """Return the publication state."""
        item = self._item()
        if item is None:
            return None
        if self.kind == KIND_SLIDE:
            return slide_status(item)
        if self.kind == KIND_NEWS:
            return information_status(item)
        return "available"

    @property
    def extra_state_attributes(self) -> Mapping[str, Any]:
        """Return useful fields for this published item."""
        item = self._item()
        if item is None:
            return {}
        if self.kind == KIND_SLIDE:
            return {
                "content_type": "slide",
                "name": item.get("name"),
                "active": item.get("active"),
                "timeslots": item.get("timeslots") or [],
                "frames": item.get("frames") or [],
            }
        summary = information_summary(item)
        summary["content_type"] = (
            "news" if self.kind == KIND_NEWS else "useful_info"
        )
        if self.kind == KIND_USEFUL:
            summary["related_links"] = _useful_links(
                self.coordinator.data, self.item_id
            )
        return summary


def _dynamic_unique_id(
    entry: CentoAccessConfigEntry, kind: str, item_id: str
) -> str:
    return f"{entry.entry_id}_{kind}_{item_id}"


def _registered_dynamic_keys(
    registry: er.EntityRegistry, entry: CentoAccessConfigEntry
) -> set[DynamicKey]:
    keys: set[DynamicKey] = set()
    for registry_entry in er.async_entries_for_config_entry(
        registry, entry.entry_id
    ):
        for kind in (KIND_NEWS, KIND_SLIDE, KIND_USEFUL):
            prefix = f"{entry.entry_id}_{kind}_"
            if registry_entry.unique_id.startswith(prefix):
                keys.add((kind, registry_entry.unique_id.removeprefix(prefix)))
                break
    return keys


def _dynamic_keys(data: CommuneData) -> set[DynamicKey]:
    keys = {
        (KIND_NEWS, str(item["id"]))
        for item in data.news
        if item.get("id") is not None
    }
    keys.update(
        (KIND_USEFUL, str(item["id"]))
        for item in data.useful_info
        if item.get("id") is not None
    )
    keys.update(
        (KIND_SLIDE, str(item["id"]))
        for item in panel_slides(data.panel_data)
        if item.get("id") is not None
    )
    return keys


def _find_dynamic_item(
    data: CommuneData, kind: str, item_id: str
) -> dict[str, Any] | None:
    if kind == KIND_NEWS:
        items = data.news
    elif kind == KIND_USEFUL:
        items = data.useful_info
    else:
        items = panel_slides(data.panel_data)
    return next(
        (item for item in items if str(item.get("id")) == item_id), None
    )


def _item_name(kind: str, item: dict[str, Any] | None, item_id: str) -> str:
    labels = {
        KIND_NEWS: "Actualité",
        KIND_SLIDE: "Diapositive",
        KIND_USEFUL: "Information pratique",
    }
    if item:
        title = item.get("title") or item.get("name")
        if title:
            return str(title)
    return f"{labels[kind]} {item_id}"


def _useful_links(data: CommuneData, item_id: str) -> list[dict[str, Any]]:
    links: list[JsonObject] = []
    for item in data.useful_info_links:
        parent = item.get("usefulInfoParent") or item.get("parent")
        parent_id = (
            as_object(cast(object, parent)).get("id")
            if isinstance(parent, dict)
            else parent
        )
        parent_id = item.get("usefulInfoParentId", parent_id)
        normalized_parent_id = str(parent_id).rstrip("/").rsplit("/", 1)[-1]
        if normalized_parent_id == item_id:
            links.append(information_summary(item))
    return links
