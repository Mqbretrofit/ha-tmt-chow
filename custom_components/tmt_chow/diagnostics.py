"""Diagnostics support for TMT Chow."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.redact import async_redact_data

from .const import CONF_CERTIFICATE_ARN, CONF_CERTIFICATE_PEM, CONF_PRIVATE_KEY, DOMAIN
from .hub import TmtChowHub

_REDACT = {CONF_CERTIFICATE_PEM, CONF_PRIVATE_KEY, CONF_CERTIFICATE_ARN}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    hub: TmtChowHub = hass.data[DOMAIN][entry.entry_id]
    return {
        "entry": async_redact_data(dict(entry.data), _REDACT),
        "runtime": {
            "available": hub.available,
            "mqtt_connected": hub.mqtt_connected,
            "device_online": hub.device_online,
            "position": hub.position,
            "movement": hub.movement,
            "is_operating": hub.is_operating,
            "battery_percent": hub.battery_percent,
            "controller_type": hub.controller_type,
            "controller_family": hub.controller_family,
            "parameter_schema_verified": hub.parameter_schema_verified,
            "parameters": hub.parameters,
            "attributes": hub.attributes,
        },
    }
