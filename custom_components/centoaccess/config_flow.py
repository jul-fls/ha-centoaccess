"""UI setup for one CentoAccess commune."""

from __future__ import annotations

import re
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .api import CentoAccessClient, CentoAccessError
from .const import (
    CONF_APPLICATION_ID,
    CONF_APPLICATION_NAME,
    CONF_COMMUNE,
    CONF_INSEE,
    CONF_LATITUDE,
    CONF_LOCATION_LABEL,
    CONF_LOCATION_SOURCE,
    CONF_LONGITUDE,
    CONF_POSTAL_CODE,
    DOMAIN,
)
from .location import (
    AmbiguousLocation,
    InvalidLocation,
    Location,
    PostalChoice,
    from_address,
    from_coordinates,
    from_insee,
    from_postal_choice,
    matching_applications,
    search_postal_prefix,
)

CONF_POSTAL_CHOICE = "postal_choice"
CONF_ADDRESS = "address"


class CentoAccessConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure a location and verify that its commune uses CentoAccess."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize transient setup state."""
        self._location: Location | None = None
        self._applications: dict[str, dict[str, Any]] = {}

    def _session(self) -> aiohttp.ClientSession:
        return async_get_clientsession(self.hass)

    async def _resolve(self, operation):
        try:
            return await operation
        except InvalidLocation:
            return "invalid_location"
        except AmbiguousLocation:
            return "ambiguous_location"
        except (aiohttp.ClientError, TimeoutError):
            return "cannot_connect"
        except (KeyError, TypeError, ValueError):
            return "invalid_location"

    async def _find_centoaccess(self, location: Location):
        """Find the exact CentoAccess application for an official commune."""
        client = CentoAccessClient(self._session())
        try:
            results = await client.search_applications(location.commune)
            matches = matching_applications(location.commune, results)
            if not matches and location.postcode:
                results = await client.search_applications(location.postcode)
                matches = matching_applications(location.commune, results)
        except (CentoAccessError, aiohttp.ClientError, TimeoutError):
            return "cannot_connect"

        applications = {
            str(application["id"]): application
            for application in matches
        }
        if not applications:
            return "not_centoaccess"
        self._location = location
        self._applications = applications
        if len(applications) == 1:
            return await self._create_entry(next(iter(applications)))
        return await self.async_step_cento_select()

    async def _create_entry(self, application_id: str) -> ConfigFlowResult:
        """Create a config entry for the selected CentoAccess application."""
        if self._location is None or application_id not in self._applications:
            return self.async_abort(reason="invalid_location")
        application = self._applications[application_id]
        location = self._location
        name = str(application.get("name") or location.commune)
        await self.async_set_unique_id(f"application_{application_id}")
        self._abort_if_unique_id_configured()
        data: dict[str, Any] = {
            CONF_APPLICATION_ID: int(application_id),
            CONF_APPLICATION_NAME: name,
            CONF_INSEE: location.code,
            CONF_COMMUNE: location.commune,
            CONF_LOCATION_SOURCE: location.source,
            CONF_LOCATION_LABEL: location.label,
        }
        if location.postcode:
            data[CONF_POSTAL_CODE] = location.postcode
        if location.latitude is not None and location.longitude is not None:
            data[CONF_LATITUDE] = location.latitude
            data[CONF_LONGITUDE] = location.longitude
        return self.async_create_entry(title=name, data=data)

    async def async_step_user(self, user_input=None):
        """Choose how the commune should be located."""
        errors = {}
        if user_input is not None:
            mode = user_input[CONF_LOCATION_SOURCE]
            if mode == "home":
                result = await self._resolve(
                    from_coordinates(
                        self._session(),
                        self.hass.config.latitude,
                        self.hass.config.longitude,
                        "home",
                    )
                )
                if isinstance(result, Location):
                    outcome = await self._find_centoaccess(result)
                    if not isinstance(outcome, str):
                        return outcome
                    errors["base"] = outcome
                else:
                    errors["base"] = result
            else:
                steps = {
                    "gps": self.async_step_gps,
                    "postal_commune": self.async_step_postal_commune,
                    "address": self.async_step_address,
                    "insee": self.async_step_insee,
                }
                return await steps[mode]()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_LOCATION_SOURCE, default="home"): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                "home",
                                "gps",
                                "postal_commune",
                                "address",
                                "insee",
                            ],
                            translation_key=CONF_LOCATION_SOURCE,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
            errors=errors,
        )

    async def async_step_gps(self, user_input=None):
        """Resolve manually entered GPS coordinates."""
        errors = {}
        if user_input is not None:
            result = await self._resolve(
                from_coordinates(
                    self._session(),
                    user_input[CONF_LATITUDE],
                    user_input[CONF_LONGITUDE],
                )
            )
            if isinstance(result, Location):
                outcome = await self._find_centoaccess(result)
                if not isinstance(outcome, str):
                    return outcome
                errors["base"] = outcome
            else:
                errors["base"] = result
        return self.async_show_form(
            step_id="gps",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_LATITUDE): vol.All(
                        vol.Coerce(float), vol.Range(min=-90, max=90)
                    ),
                    vol.Required(CONF_LONGITUDE): vol.All(
                        vol.Coerce(float), vol.Range(min=-180, max=180)
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_postal_commune(self, user_input=None):
        """Search official communes by a two-to-five digit postal prefix."""
        errors = {}
        if user_input is not None:
            prefix = user_input[CONF_POSTAL_CODE].strip()
            if not re.fullmatch(r"\d{2,5}", prefix):
                errors[CONF_POSTAL_CODE] = "invalid_postal_prefix"
            else:
                result = await self._resolve(
                    search_postal_prefix(self._session(), prefix)
                )
                if isinstance(result, list):
                    self._postal_choices: dict[str, PostalChoice] = {
                        choice.value: choice for choice in result
                    }
                    return await self.async_step_postal_select()
                errors["base"] = result
        return self.async_show_form(
            step_id="postal_commune",
            data_schema=vol.Schema({vol.Required(CONF_POSTAL_CODE): str}),
            errors=errors,
        )

    async def async_step_postal_select(self, user_input=None):
        """Select one official commune from postal search results."""
        choices = getattr(self, "_postal_choices", None)
        if not choices:
            return await self.async_step_postal_commune()
        errors = {}
        if user_input is not None:
            selected = choices.get(user_input.get(CONF_POSTAL_CHOICE))
            if selected is None:
                errors["base"] = "invalid_location"
            else:
                result = await self._resolve(
                    from_postal_choice(self._session(), selected)
                )
                if isinstance(result, Location):
                    outcome = await self._find_centoaccess(result)
                    if not isinstance(outcome, str):
                        return outcome
                    errors["base"] = outcome
                else:
                    errors["base"] = result
        options = [
            SelectOptionDict(value=choice.value, label=choice.label)
            for choice in choices.values()
        ]
        return self.async_show_form(
            step_id="postal_select",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_POSTAL_CHOICE): SelectSelector(
                        SelectSelectorConfig(
                            options=options, mode=SelectSelectorMode.DROPDOWN
                        )
                    )
                }
            ),
            errors=errors,
        )

    async def async_step_address(self, user_input=None):
        """Resolve a complete address."""
        errors = {}
        if user_input is not None:
            result = await self._resolve(
                from_address(self._session(), user_input[CONF_ADDRESS])
            )
            if isinstance(result, Location):
                outcome = await self._find_centoaccess(result)
                if not isinstance(outcome, str):
                    return outcome
                errors["base"] = outcome
            else:
                errors["base"] = result
        return self.async_show_form(
            step_id="address",
            data_schema=vol.Schema({vol.Required(CONF_ADDRESS): str}),
            errors=errors,
        )

    async def async_step_insee(self, user_input=None):
        """Resolve an INSEE commune code."""
        errors = {}
        if user_input is not None:
            result = await self._resolve(
                from_insee(self._session(), user_input[CONF_INSEE])
            )
            if isinstance(result, Location):
                outcome = await self._find_centoaccess(result)
                if not isinstance(outcome, str):
                    return outcome
                errors["base"] = outcome
            else:
                errors["base"] = result
        return self.async_show_form(
            step_id="insee",
            data_schema=vol.Schema({vol.Required(CONF_INSEE): str}),
            errors=errors,
        )

    async def async_step_cento_select(self, user_input=None):
        """Select one application if a commune has multiple CentoAccess apps."""
        if not self._applications:
            return self.async_abort(reason="invalid_location")
        if user_input is not None:
            return await self._create_entry(user_input[CONF_APPLICATION_ID])
        options = [
            SelectOptionDict(
                value=application_id,
                label=str(application.get("name") or application_id),
            )
            for application_id, application in self._applications.items()
        ]
        return self.async_show_form(
            step_id="cento_select",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_APPLICATION_ID): SelectSelector(
                        SelectSelectorConfig(
                            options=options, mode=SelectSelectorMode.DROPDOWN
                        )
                    )
                }
            ),
        )
