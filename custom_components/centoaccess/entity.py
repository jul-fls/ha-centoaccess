"""Shared entity helpers for CentoAccess."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.helpers.device_registry import DeviceInfo

from .api import CommuneData
from .const import DOMAIN
from .models import absolute_url, as_object

if TYPE_CHECKING:
    from . import CentoAccessConfigEntry


def device_info(entry: CentoAccessConfigEntry, data: CommuneData) -> DeviceInfo:
    """Describe one configured CentoAccess commune."""
    small_client = as_object(data.application.get("smallClient"))
    info: DeviceInfo = {
        "identifiers": {(DOMAIN, str(data.application_id))},
        "name": f"CentoAccess - {data.name}",
        "manufacturer": "Centaure-Systems",
        "model": f"Application municipale / client {small_client.get('id', 'inconnu')}",
    }
    if data.panel_url:
        info["configuration_url"] = absolute_url(data.panel_url)
    return info
