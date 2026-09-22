"""Sensors for CentoAccess."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import CentoAccessConfigEntry
from .entity import CentoAccessEntityMixin
from .models import information_summary, panel_slides


@dataclass(frozen=True, kw_only=True)
class CentoAccessSensorDescription(SensorEntityDescription):
    """Describe a CentoAccess sensor."""

    value_fn: Callable[[Any], Any]
    attributes_fn: Callable[[Any], Mapping[str, Any]]


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
            "slides": panel_slides(data.panel_data),
        },
    ),
    CentoAccessSensorDescription(
        key="agenda",
        translation_key="agenda",
        icon="mdi:calendar-month-outline",
        value_fn=lambda data: len(data.events),
        attributes_fn=lambda data: {
            "items": [information_summary(item) for item in data.events]
        },
    ),
    CentoAccessSensorDescription(
        key="news",
        translation_key="news",
        icon="mdi:newspaper-variant-outline",
        value_fn=lambda data: len(data.news),
        attributes_fn=lambda data: {
            "items": [information_summary(item) for item in data.news]
        },
    ),
    CentoAccessSensorDescription(
        key="useful_info",
        translation_key="useful_info",
        icon="mdi:information-outline",
        value_fn=lambda data: len(data.useful_info),
        attributes_fn=lambda data: {
            "items": [information_summary(item) for item in data.useful_info],
            "links": [
                information_summary(item) for item in data.useful_info_links
            ],
        },
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CentoAccessConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up CentoAccess sensors."""
    async_add_entities(
        CentoAccessSensor(entry, description) for description in SENSORS
    )


class CentoAccessSensor(
    CentoAccessEntityMixin, CoordinatorEntity, SensorEntity
):
    """Representation of a CentoAccess sensor."""

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
        self._set_device_info(entry)

    @property
    def native_value(self) -> Any:
        """Return the sensor value."""
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> Mapping[str, Any]:
        """Return detailed commune data."""
        return self.entity_description.attributes_fn(self.coordinator.data)
