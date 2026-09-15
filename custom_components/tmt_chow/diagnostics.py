"""Diagnostics support for TMT Chow, including the PS25007A AutoProduct alias."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .diagnostics_base import async_get_config_entry_diagnostics as _base_diagnostics
from .pedestrian import PEDESTRIAN_STRATEGY_PED_OPEN

_PS25007_APP_MODEL = "PS25007"
_PS25007A_CONTROLLER_TYPE = "PS25007A"


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict:
    """Return normal diagnostics with explicit PS25007A verified metadata."""
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
        }
    )

    # diagnostics_base intentionally keeps the generic PS25007/PS25007A deny
    # list visible. Override only the effective runtime result for the exact
    # verified alias/context handled by ps25007a_hub.
    runtime["pedestrian_strategy"] = hub.pedestrian_strategy
    if (
        hub.controller_type == _PS25007A_CONTROLLER_TYPE
        and hub.pedestrian_strategy == PEDESTRIAN_STRATEGY_PED_OPEN
    ):
        runtime.update(
            {
                "pedestrian_strategy_reason": "ps25007a_identified_source_real_hardware_verified",
                "pedestrian_direct_command_blocked": False,
                "pedestrian_ack_policy": "no_ack_expected_use_status_position_telemetry",
                "pedestrian_retry_policy": "never_retry",
                "pedestrian_verified_start_condition": "fully_closed_and_stopped",
            }
        )
    return result
