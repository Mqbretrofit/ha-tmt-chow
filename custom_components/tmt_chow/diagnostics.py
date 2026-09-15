"""Diagnostics support for TMT Chow, including the PS25007A AutoProduct alias."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .diagnostics_base import async_get_config_entry_diagnostics as _base_diagnostics

_PS25007_APP_MODEL = "PS25007"
_PS25007A_CONTROLLER_TYPE = "PS25007A"


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict:
    """Return normal diagnostics with explicit PS25007A codec/test metadata."""
    result = await _base_diagnostics(hass, entry)
    hub = hass.data[DOMAIN][entry.entry_id]
    if not (
        hub.configured_controller_type == _PS25007_APP_MODEL
        and hub.parameter_model_type == _PS25007A_CONTROLLER_TYPE
    ):
        return result

    runtime = result.get("runtime", {})
    runtime.update(
        {
            "parameter_codec_available": True,
            "parameter_uart_version": 1,
            "parameter_skip_positions": [],
            "parameter_codec_profile": "ps25007a_wire17",
            "parameter_extended_suffix": "",
            "parameter_expected_wire_token_count": 17,
            "parameter_value_mapping_profile": "ps25007_proposal_wire17",
            "ps25007a_pedestrian_test": hub.ps25007a_ped_test_diagnostics,
        }
    )
    return result
