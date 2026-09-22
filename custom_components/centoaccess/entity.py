"""Shared entity helpers for CentoAccess."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity import DeviceInfo

from .api import CommuneData
from .const import DOMAIN
from .models import absolute_url


def device_info(entry: ConfigEntry, data: CommuneData) -> DeviceInfo:
    """Describe one configured CentoAccess commune."""
    small_client = data.application.get("smallClient") or {}
    info: DeviceInfo = {
        "identifiers": {(DOMAIN, str(data.application_id))},
        "name": f"CentoAccess - {data.name}",
        "manufacturer": "Centaure-Systems",
        "model": f"Application municipale / client {small_client.get('id', 'inconnu')}",
    }
    if data.panel_url:
        info["configuration_url"] = absolute_url(data.panel_url)
    return info


class CentoAccessEntityMixin:
    """Attach CentoAccess entities to their commune device."""

    _attr_device_info: DeviceInfo

    def _set_device_info(self, entry: ConfigEntry) -> None:
        """Set device information from the coordinator's current data."""
        self._attr_device_info = device_info(entry, self.coordinator.data)
