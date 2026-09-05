"""Diagnostics support for TMT Chow."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.redact import async_redact_data

from .const import CONF_CERTIFICATE_ARN, CONF_CERTIFICATE_PEM, CONF_PRIVATE_KEY, DOMAIN
from .hub import TmtChowHub
from .model_parameter_schemas import parameter_name, parameter_options
from .model_protocol_profiles import protocol_profile_for

_REDACT = {CONF_CERTIFICATE_PEM, CONF_PRIVATE_KEY, CONF_CERTIFICATE_ARN}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    hub: TmtChowHub = hass.data[DOMAIN][entry.entry_id]
    profile = protocol_profile_for(hub.parameter_model_type)
    schema = hub.model_parameter_schema
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
            "configured_controller_type": hub.configured_controller_type,
            "controller_family": hub.controller_family,
            "controller_capabilities": sorted(hub.controller_capabilities),
            "product_type": hub.product_type,
            "parameter_model_type": hub.parameter_model_type,
            "parameter_model_source": hub.parameter_model_source,
            "model_parameter_schema_available": schema is not None,
            "model_parameter_schema_count": len(schema or ()),
            "parameter_codec_available": profile is not None,
            "parameter_uart_version": profile[0] if profile is not None else None,
            "parameter_skip_positions": list(profile[1]) if profile is not None else [],
            "parameter_codec_profile": profile[2] if profile is not None else None,
            "parameter_extended_suffix": profile[3] if profile is not None else "",
            "parameter_write_schema_verified": hub.parameter_write_schema_verified,
            "model_parameter_schema": [
                {
                    "index": index,
                    "key": spec[1],
                    "name": parameter_name(spec),
                    "kind": spec[0],
                    "option_key": spec[2],
                    "options": list(parameter_options(spec)),
                    "parameter_type": spec[3],
                    "level": spec[4],
                    "default": spec[5],
                    "offset": spec[6],
                    "max_value_hint": spec[7],
                    "bit_index": spec[8],
                    "big_endian": spec[9],
                    "bit_count": spec[10],
                    "minimum": spec[11],
                    "maximum": spec[12],
                    "increment": spec[13],
                    "multiple": spec[14],
                    "unit_key": spec[15],
                    "off_value": spec[16],
                }
                for index, spec in enumerate(schema or (), start=1)
            ],
            "parameters": hub.parameters,
            "attributes": hub.attributes,
        },
    }
