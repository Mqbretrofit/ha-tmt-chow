"""Diagnostics support for TMT Chow."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.redact import async_redact_data

from .const import (
    ATTR_DEV_PARAM,
    ATTR_LAST_RESPONSE,
    CONF_CERTIFICATE_ARN,
    CONF_CERTIFICATE_PEM,
    CONF_ENDPOINT,
    CONF_OURANOS_PIN,
    CONF_PRIVATE_KEY,
    CONF_THING_NAME,
    CONF_UUID,
    DOMAIN,
    OURANOS_POLLERS_DATA_KEY,
    OURANOS_STATUS_AVAILABILITY_SECONDS,
    OURANOS_STATUS_FAILURE_RETRY_SECONDS,
    OURANOS_STATUS_POLL_SECONDS,
)
from .hub import TmtChowHub, TmtCommandError
from .model_parameter_schemas import parameter_name, parameter_options
from .model_protocol_profiles import protocol_profile_for
from .pedestrian import (
    PEDESTRIAN_STRATEGY_RELAY4,
    direct_ped_open_blocked,
    pedestrian_strategy_for,
    pedestrian_strategy_reason,
)
from .ps21050d_parameters import (
    CONTROLLER_TYPE as PS21050D,
    UART_VERSION as PS21050D_UART_VERSION,
    parameter_options_for as ps21050d_parameter_options,
)
from .ps22027_parameters import (
    CONTROLLER_TYPE as PS22027,
    decoded_parameter_values as ps22027_decoded_parameter_values,
    parameter_options_for as ps22027_parameter_options,
)
from .shadow_diagnostics import async_probe_shadow_get
from .status_diagnostics import async_probe_status_read

_REDACT = {
    CONF_CERTIFICATE_PEM,
    CONF_PRIVATE_KEY,
    CONF_CERTIFICATE_ARN,
    CONF_OURANOS_PIN,
}


def _inspect_parameter_payload(payload: Any) -> dict[str, Any] | None:
    """Return wire-level details without trying to reinterpret the values."""
    if not isinstance(payload, str) or not payload.strip():
        return None

    clean = payload.split(";", 1)[0].strip()
    body = clean
    ack_prefix: str | None = None
    ack_separator: str | None = None

    for prefix in ("ACK RP,1", "ACK RP", "ACK READ FUNCTION"):
        if not clean.startswith(prefix):
            continue
        ack_prefix = prefix
        tail = clean[len(prefix) :]
        if tail[:1] in {":", ","}:
            ack_separator = tail[0]
            body = tail[1:]
        else:
            body = tail.lstrip()
        break

    body = body.lstrip(":")
    tokens = body.split(",") if body else []
    return {
        "raw": payload,
        "clean": clean,
        "ack_prefix": ack_prefix,
        "ack_separator": ack_separator,
        "body": body,
        "token_count": len(tokens),
        "empty_token_positions": [
            index for index, token in enumerate(tokens) if token == ""
        ],
        "tokens": tokens,
    }


def _expected_wire_token_count(schema: tuple | None, profile: tuple | None) -> int | None:
    """Return the exact minimum token count for simple APK codec profiles."""
    if schema is None or profile is None:
        return None

    codec_profile = profile[2]
    if codec_profile not in {"legacy_base", "new_phase1", "custom_p170"}:
        return None

    skip_positions = set(profile[1])
    wire = 0
    for spec in schema:
        parameter_type = int(spec[3] or 0)
        if parameter_type >= 10:
            continue
        count = 1
        if codec_profile in {"new_phase1", "custom_p170"}:
            bit_count = int(spec[10] or 0)
            count = bit_count if bit_count > 0 else 1
        for _ in range(count):
            while wire in skip_positions:
                wire += 1
            wire += 1
    return wire


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    hub: TmtChowHub = hass.data[DOMAIN][entry.entry_id]
    ouranos_poller = hass.data.get(OURANOS_POLLERS_DATA_KEY, {}).get(entry.entry_id)

    # Probe the classic AWS IoT Shadow GET path using an isolated read-only MQTT
    # connection. This distinguishes accepted/rejected/no-response without
    # changing the live hub subscriptions or publishing to any gate command topic.
    shadow_get_probe = await async_probe_shadow_get(
        endpoint=str(entry.data.get(CONF_ENDPOINT) or ""),
        uuid=str(entry.data.get(CONF_UUID) or ""),
        thing_name=str(entry.data.get(CONF_THING_NAME) or ""),
        certificate_pem=str(entry.data.get(CONF_CERTIFICATE_PEM) or ""),
        private_key=str(entry.data.get(CONF_PRIVATE_KEY) or ""),
    )

    # Independently test the legacy WBT status-read path. This sends exactly one
    # read-only c=RS request and waits for ACK RS without touching movement or
    # parameter-write commands. It is especially useful for devices without a
    # classic AWS IoT Shadow.
    status_read_probe = await async_probe_status_read(
        endpoint=str(entry.data.get(CONF_ENDPOINT) or ""),
        uuid=str(entry.data.get(CONF_UUID) or ""),
        certificate_pem=str(entry.data.get(CONF_CERTIFICATE_PEM) or ""),
        private_key=str(entry.data.get(CONF_PRIVATE_KEY) or ""),
    )

    # If the normal bootstrap failed, perform one additional read-only probe while
    # diagnostics are being generated. This captures the parameter ACK immediately
    # in ATTR_LAST_RESPONSE, instead of letting later status traffic overwrite it.
    parameter_probe_attempted = False
    parameter_probe_error: dict[str, str] | None = None
    if hub.parameters is None and hub.may_probe_parameters:
        parameter_probe_attempted = True
        try:
            await hub.async_refresh_parameters()
        except TmtCommandError as err:
            parameter_probe_error = {
                "message": str(err),
                "translation_key": err.translation_key,
            }

    is_ps21050d_alias = (
        hub.parameter_model_type == PS21050D
        and hub.parameter_model_source == "apk_ps21050_alias"
    )
    is_ps22027_profile = (
        hub.parameter_model_type == PS22027
        and hub.parameter_model_source
        in {"ps22027_wire20_read_only", "ps22027_wire20_verified"}
    )
    profile = (
        (PS21050D_UART_VERSION, (), "ps21050_app_wire20", "")
        if hub.parameter_model_type == PS21050D
        else protocol_profile_for(hub.parameter_model_type)
    )
    schema = hub.model_parameter_schema
    last_response_debug = _inspect_parameter_payload(
        hub.attributes.get(ATTR_LAST_RESPONSE)
    )
    shadow_parameter_debug = _inspect_parameter_payload(
        hub.attributes.get(ATTR_DEV_PARAM)
    )
    expected_wire_tokens = _expected_wire_token_count(schema, profile)
    pedestrian_strategy = pedestrian_strategy_for(
        hub.controller_type,
        hub.controller_capabilities,
    )
    direct_blocked = direct_ped_open_blocked(
        hub.controller_type
    ) or direct_ped_open_blocked(hub.configured_controller_type)

    return {
        "entry": async_redact_data(dict(entry.data), _REDACT),
        "options": async_redact_data(dict(entry.options), _REDACT),
        "runtime": {
            "available": hub.available,
            "mqtt_connected": hub.mqtt_connected,
            "ouranos_status_enabled": bool(entry.options.get(CONF_OURANOS_PIN)),
            "ouranos_status_available": hub.ouranos_status_available,
            "ouranos_status_age_seconds": (
                round(hub.ouranos_status_age_seconds, 1)
                if hub.ouranos_status_age_seconds is not None
                else None
            ),
            "ouranos_status_poll_seconds": OURANOS_STATUS_POLL_SECONDS,
            "ouranos_status_failure_retry_seconds": (
                OURANOS_STATUS_FAILURE_RETRY_SECONDS
            ),
            "ouranos_status_availability_seconds": (
                OURANOS_STATUS_AVAILABILITY_SECONDS
            ),
            "ouranos_status_last_result": (
                ouranos_poller.last_result if ouranos_poller is not None else None
            ),
            "ouranos_status_last_attempt_at": (
                ouranos_poller.last_attempt_at if ouranos_poller is not None else None
            ),
            "ouranos_status_last_success_at": (
                ouranos_poller.last_success_at if ouranos_poller is not None else None
            ),
            "ouranos_status_consecutive_failures": (
                ouranos_poller.consecutive_failures
                if ouranos_poller is not None
                else None
            ),
            "ouranos_status_refresh_in_progress": (
                ouranos_poller.refresh_in_progress
                if ouranos_poller is not None
                else False
            ),
            "ouranos_status_session_connected": (
                ouranos_poller.session_connected
                if ouranos_poller is not None
                else False
            ),
            "shadow_get_probe_result": shadow_get_probe["result"],
            "shadow_get_rejection_code": shadow_get_probe["rejection_code"],
            "shadow_get_rejection_message": shadow_get_probe["rejection_message"],
            "shadow_get_probe_error": shadow_get_probe["probe_error"],
            "status_read_probe_result": status_read_probe["result"],
            "status_read_probe_ack": status_read_probe["ack"],
            "status_read_probe_parsed": status_read_probe["parsed"],
            "status_read_probe_position": status_read_probe["position"],
            "status_read_probe_is_operating": status_read_probe["is_operating"],
            "status_read_probe_open_direction": status_read_probe["open_direction"],
            "status_read_probe_battery_percent": status_read_probe["battery_percent"],
            "status_read_probe_error": status_read_probe["probe_error"],
            "device_online": hub.device_online,
            "position": hub.position,
            "movement": hub.movement,
            "is_operating": hub.is_operating,
            "battery_percent": hub.battery_percent,
            "controller_type": hub.controller_type,
            "configured_controller_type": hub.configured_controller_type,
            "controller_family": hub.controller_family,
            "controller_capabilities": sorted(hub.controller_capabilities),
            "pedestrian_strategy": pedestrian_strategy,
            "pedestrian_strategy_reason": pedestrian_strategy_reason(
                hub.controller_type,
                hub.controller_capabilities,
            ),
            "pedestrian_direct_command_blocked": direct_blocked,
            "pedestrian_relay4_enabled": pedestrian_strategy == PEDESTRIAN_STRATEGY_RELAY4,
            # TMT Chow 3.1.4 AutoProduct can select RELAY4 from its cloud
            # FunctionSet, but the current HA runtime does not receive that
            # proposal payload. Keep these explicit in diagnostics so missing
            # FunctionSet evidence is visible instead of being guessed.
            "function_set_evidence_available": False,
            "function_set_pedestrian": None,
            "relay4_available": None,
            "relay4_function_name": None,
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
            "parameter_expected_wire_token_count": expected_wire_tokens,
            "parameter_probe_attempted": parameter_probe_attempted,
            "parameter_probe_error": parameter_probe_error,
            "parameter_last_response_debug": last_response_debug,
            "parameter_shadow_payload_debug": shadow_parameter_debug,
            "parameter_write_schema_verified": hub.parameter_write_schema_verified,
            "parameter_read_only": (
                hub.parameter_schema_verified
                and not hub.parameter_write_schema_verified
            ),
            "parameter_value_mapping_profile": (
                "ps22027_apk_hall_helper_write_verified"
                if is_ps22027_profile and hub.parameter_write_schema_verified
                else "ps22027_apk_hall_helper_read_only"
                if is_ps22027_profile
                else None
            ),
            "parameter_decoded_values": (
                ps22027_decoded_parameter_values(hub.parameters)
                if is_ps22027_profile
                else None
            ),
            "model_parameter_schema": [
                {
                    "index": index,
                    "key": spec[1],
                    "name": parameter_name(spec),
                    "kind": spec[0],
                    "option_key": spec[2],
                    "options": list(
                        ps21050d_parameter_options(index - 1, hub.parameters)
                        if is_ps21050d_alias
                        else ps22027_parameter_options(index - 1, hub.parameters)
                        if is_ps22027_profile
                        else parameter_options(spec)
                    ),
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
