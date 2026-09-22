"""CentoAccess integration for Home Assistant."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import logging

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import CentoAccessClient, CentoAccessError, CommuneData
from .const import CONF_APPLICATION_ID, DOMAIN, SCAN_INTERVAL_MINUTES

LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.SENSOR, Platform.CALENDAR]


@dataclass
class CentoAccessRuntimeData:
    """Runtime data kept on the config entry."""

    coordinator: DataUpdateCoordinator[CommuneData]


type CentoAccessConfigEntry = ConfigEntry[CentoAccessRuntimeData]


async def async_setup_entry(
    hass: HomeAssistant, entry: CentoAccessConfigEntry
) -> bool:
    """Set up CentoAccess from a config entry."""
    client = CentoAccessClient(async_get_clientsession(hass))
    application_id = entry.data[CONF_APPLICATION_ID]

    async def async_update_data() -> CommuneData:
        try:
            return await client.fetch(application_id)
        except (CentoAccessError, aiohttp.ClientError, TimeoutError) as error:
            raise UpdateFailed(f"Unable to update CentoAccess data: {error}") from error

    coordinator = DataUpdateCoordinator(
        hass,
        LOGGER,
        name=f"{DOMAIN}_{application_id}",
        update_method=async_update_data,
        update_interval=timedelta(minutes=SCAN_INTERVAL_MINUTES),
    )
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = CentoAccessRuntimeData(coordinator=coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: CentoAccessConfigEntry
) -> bool:
    """Unload a CentoAccess config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
