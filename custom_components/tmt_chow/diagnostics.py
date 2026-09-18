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
    CONF_PROPOSAL,
    CONF_PROPOSAL_FETCH_STATUS,
    CONF_PROPOSAL_ID,
    CONF_THING_NAME,
    CONF_UUID,
    CONF_UUID_TYPE,
    DOMAIN,
    OURANOS_POLLERS_DATA_KEY,
    OURANOS_STATUS_AVAILABILITY_SECONDS,
    OURANOS_STATUS_FAILURE_RETRY_SECONDS,
    OURANOS_STATUS_POLL_SECONDS,
)
from .hub import TmtChowHub, TmtCommandError
from .model_parameter_schemas import parameter_name, parameter_options
from .model_protocol_profiles import protocol_profile_for
from .ouranos_ha_probe import async_probe_ouranos_on_ha
from .pedestrian import (
    PEDESTRIAN_STRATEGY_RELAY4,
    direct_ped_open_blocked,
    pedestrian_strategy_for,
    pedestrian_strategy_reason,
)
from .proposal import (
    normalize_proposal_payload,
    proposal_function_labels,
    proposal_summary,
    redact_proposal_payload,
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
from .ps22087b_parameters import (
    CONTROLLER_TYPE as PS22087B,
    PARAMETERS as PS22087B_PARAMETERS,
)
from .ps25142_parameters import (
    CONTROLLER_TYPE as PS25142,
    PARAMETER_COUNT as PS25142_PARAMETER_COUNT,
    PS25142_PARAMETERS,
)
from .shadow_diagnostics import async_probe_shadow_get
from .status_diagnostics import (
    async_probe_parameter_read,
    async_probe_status_read,
    async_probe_wbt_read_matrix,
)

_REDACT = {
    CONF_CERTIFICATE_PEM,
    CONF_PRIVATE_KEY,
    CONF_CERTIFICATE_ARN,
    CONF_OURANOS_PIN,
    # The raw cloud proposal can contain userEmail.  Expose only the recursively
    # sanitized copy below so personal data never leaks through entry diagnostics.
    CONF_PROPOSAL,
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


def _needs_controller_discovery(hub: TmtChowHub) -> bool:
    """Return whether one broad read-only route matrix adds useful evidence."""
    return (
        hub.controller_type is None
        or hub.controller_family is None
        or hub.model_parameter_schema is None
        or not hub.parameter_schema_verified
        or hub.parameter_model_source in {None, "controller", "configured_fallback"}
    )


async def _async_probe_ouranos_read_matrix(
    hass: HomeAssistant,
    *,
    uuid: str,
    uuid_type: Any,
    pin_code: str,
) -> dict[str, Any] | None:
    """Probe both known read-only native status dialects for OURANOS candidates."""
    if str(uuid_type or "").strip() != "1" or len(uuid) != 20:
        return None
    if len(pin_code) != 6 or not pin_code.isascii() or not pin_code.isdigit():
        return {
            "result": "not_run",
            "blocker": "save the six-digit gate PIN in integration options",
            "safety": {"read_only": True, "commands": ["READ STATUS", "RS"]},
            "results": {},
            "working_commands": [],
        }

    results = {
        "READ STATUS": await async_probe_ouranos_on_ha(
            hass, uuid, pin_code, "READ_STATUS"
        ),
        "RS": await async_probe_ouranos_on_ha(hass, uuid, pin_code, "RS"),
    }
    return {
        "result": "completed",
        "blocker": None,
        "safety": {
            "read_only": True,
            "commands_sent_once": True,
            "movement_commands_sent": False,
            "parameter_writes_sent": False,
        },
        "results": results,
        "working_commands": [
            command
            for command, result in results.items()
            if result.get("result") == "status_response_received"
        ],
    }


def _controller_route_analysis(
    *,
    hub: TmtChowHub,
    uuid_type: Any,
    proposal_info: dict[str, Any],
    shadow_probe: dict[str, Any],
    status_probe: dict[str, Any],
    parameter_probe: dict[str, Any] | None,
    wbt_matrix: dict[str, Any] | None = None,
    ouranos_matrix: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Synthesize one safe controller-discovery report from all evidence."""
    evidence: list[str] = []
    blockers: list[str] = []
    data_sources: list[dict[str, Any]] = []

    uuid_type_text = str(uuid_type or "").strip()
    if uuid_type_text:
        evidence.append(f"vendor uuid_type={uuid_type_text}")

    shadow_result = shadow_probe.get("result")
    data_sources.append(
        {
            "source": "aws_iot_classic_shadow",
            "result": shadow_result,
            "role": "initial state and reported metadata",
        }
    )
    if shadow_result == "accepted":
        evidence.append("classic AWS IoT Shadow GET accepted")

    status_result = status_probe.get("result")
    data_sources.append(
        {
            "source": "wbt_mqtt_rs",
            "result": status_result,
            "role": "live status/position probe",
            "observed_payload_count": status_probe.get("observed_payload_count"),
        }
    )
    if status_result in {"acknowledged", "traffic_observed"}:
        evidence.append(f"WBT/MQTT RS probe={status_result}")

    if parameter_probe is not None:
        data_sources.append(
            {
                "source": "wbt_mqtt_rp1",
                "result": parameter_probe.get("result"),
                "role": "UART V3 parameter read probe",
                "observed_payload_count": parameter_probe.get(
                    "observed_payload_count"
                ),
            }
        )
        if parameter_probe.get("result") in {"acknowledged", "traffic_observed"}:
            evidence.append(
                f"WBT/MQTT RP,1 probe={parameter_probe.get('result')}"
            )

    if wbt_matrix is not None:
        working = list(wbt_matrix.get("working_commands") or [])
        data_sources.append(
            {
                "source": "wbt_read_dialect_matrix",
                "result": "completed",
                "role": "discover status and parameter request dialects",
                "working_commands": working,
            }
        )
        if working:
            evidence.append("WBT read matrix responses=" + ", ".join(working))

    if ouranos_matrix is not None:
        working = list(ouranos_matrix.get("working_commands") or [])
        data_sources.append(
            {
                "source": "ouranos_read_dialect_matrix",
                "result": ouranos_matrix.get("result"),
                "role": "discover native status request dialect",
                "working_commands": working,
                "blocker": ouranos_matrix.get("blocker"),
            }
        )
        if working:
            evidence.append("OURANOS read matrix responses=" + ", ".join(working))
        if ouranos_matrix.get("blocker"):
            blockers.append(str(ouranos_matrix["blocker"]))

    if proposal_info.get("available"):
        data_sources.append(
            {
                "source": "vendor_cloud_proposal",
                "result": "available",
                "role": "controller family, UART, FunctionSet and ParameterSet",
            }
        )
        evidence.append(
            "cloud Proposal available"
            f" (uart={proposal_info.get('uart_version')},"
            f" tested={proposal_info.get('is_tested')})"
        )
    else:
        blockers.append("vendor cloud Proposal is unavailable")

    if hub.ouranos_status_available:
        data_sources.append(
            {
                "source": "ouranos_iotc_rdt",
                "result": "verified_live_status",
                "role": "native status/control transport",
            }
        )
        evidence.append("native OURANOS status response verified")

    if uuid_type_text == "1" or hub.ouranos_status_available:
        transport = "ouranos_iotc_rdt"
        transport_confidence = "verified" if hub.ouranos_status_available else "vendor_metadata"
    elif shadow_result == "accepted" or status_result in {
        "acknowledged",
        "traffic_observed",
    }:
        transport = "aws_wbt_mqtt"
        transport_confidence = "probe_confirmed"
    elif hub.mqtt_connected:
        transport = "aws_mqtt_connected_route_unconfirmed"
        transport_confidence = "partial"
        blockers.append("MQTT connects but no state/status response source is confirmed")
    else:
        transport = "unresolved"
        transport_confidence = "none"
        blockers.append("no working runtime transport was observed")

    uart_version = str(proposal_info.get("uart_version") or "").strip().upper()
    expected_status_command = (
        "READ STATUS"
        if hub.configured_controller_type == "PS19001"
        else "RS"
        if uart_version in {"V3.0", "3.0"}
        else "unknown"
    )
    expected_parameter_read = (
        "RP,1" if uart_version in {"V3.0", "3.0"} else "model/APK profile required"
    )

    if hub.controller_type is None:
        blockers.append("live DEV INFO controller identity was not received")
    if not proposal_info.get("function_set_available"):
        blockers.append("FunctionSet evidence is unavailable")
    if hub.model_parameter_schema is None:
        blockers.append("no mapped parameter schema is selected")
    if transport == "ouranos_iotc_rdt" and not hub.ouranos_status_available:
        blockers.append("one read-only native status response is still required")

    return {
        "report_version": 1,
        "purpose": "single-diagnostic controller routing discovery",
        "safety": {
            "movement_commands_sent": False,
            "parameter_writes_sent": False,
            "relay_or_learning_commands_sent": False,
            "read_only_probes_only": True,
        },
        "identity_chain": {
            "configured_controller": hub.configured_controller_type,
            "live_controller": hub.controller_type,
            "product_type": hub.product_type,
            "uuid_type": uuid_type,
            "proposal_type": proposal_info.get("proposal_type"),
            "proposal_version": proposal_info.get("proposal_version"),
            "gate_family": hub.controller_family
            or proposal_info.get("gate_family_hint"),
            "uart_version": proposal_info.get("uart_version"),
        },
        "selected_route": {
            "transport": transport,
            "confidence": transport_confidence,
            "expected_status_command": expected_status_command,
            "expected_parameter_read": expected_parameter_read,
            "runtime_state_source": (
                "classic_shadow"
                if shadow_result == "accepted"
                else "wbt_rs"
                if status_result in {"acknowledged", "traffic_observed"}
                else "ouranos_native"
                if hub.ouranos_status_available or uuid_type_text == "1"
                else "unresolved"
            ),
        },
        "vendor_capabilities": {
            "function_labels": proposal_info.get("function_labels", []),
            "parameter_count": proposal_info.get("parameter_set_count"),
            "pedestrian": proposal_info.get("pedestrian_function_present"),
            "relay4": proposal_info.get("relay4_present"),
            "is_tested": proposal_info.get("is_tested"),
        },
        "data_sources": data_sources,
        "evidence": evidence,
        "remaining_blockers": list(dict.fromkeys(blockers)),
        "implementation_readiness": (
            "mapped_and_write_verified"
            if hub.parameter_write_schema_verified
            else "mapped_read_only"
            if hub.parameter_schema_verified
            else "routing_evidence_collected"
            if transport != "unresolved"
            else "needs_transport_evidence"
        ),
    }


def _diagnostic_schema(
    hub: TmtChowHub,
    schema: tuple | None,
    *,
    is_ps21050d_alias: bool,
    is_ps22027_profile: bool,
) -> list[dict[str, Any]]:
    """Serialize standard generated schemas and the verified P710U wire schema."""
    if hub.parameter_model_type == PS25142:
        return [
            {
                "index": index,
                "key": definition.key,
                "name": definition.key,
                "kind": "option",
                "options": list(definition.options),
                "writable": True,
                "source": "PS25142 Proposal B / UART V3.0",
            }
            for index, definition in enumerate(PS25142_PARAMETERS, start=1)
        ]
    if hub.parameter_model_type == PS22087B:
        return [
            {
                "index": index,
                "key": definition.code,
                "name": definition.name,
                "kind": "option" if definition.writable else "reserved_read_only",
                "options": list(definition.options),
                "writable": definition.writable,
            }
            for index, definition in enumerate(PS22087B_PARAMETERS, start=1)
        ]
    return [
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
    ]


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    hub: TmtChowHub = hass.data[DOMAIN][entry.entry_id]
    ouranos_poller = hass.data.get(OURANOS_POLLERS_DATA_KEY, {}).get(entry.entry_id)

    proposal = normalize_proposal_payload(entry.data.get(CONF_PROPOSAL))
    proposal_info = proposal_summary(proposal)
    proposal_labels = proposal_function_labels(proposal)
    relay4_label = next(
        (
            label
            for label in proposal_labels
            if "relay 4" in label.casefold() or "relay4" in label.casefold()
        ),
        None,
    )

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

    # Independently test the WBT status-read path. The probe records every
    # wbt01Tx payload it sees, not only the integration's historic strict
    # `startswith("ACK RS:")` response shape. It still sends exactly one c=RS
    # read and never sends movement or write commands.
    status_read_probe = await async_probe_status_read(
        endpoint=str(entry.data.get(CONF_ENDPOINT) or ""),
        uuid=str(entry.data.get(CONF_UUID) or ""),
        certificate_pem=str(entry.data.get(CONF_CERTIFICATE_PEM) or ""),
        private_key=str(entry.data.get(CONF_PRIVATE_KEY) or ""),
    )

    # TMT Chow 3.2.0 maps cloud uartVer V3.0 to its UART1 AutoProduct path.
    # The vendor read command on that path is RP,1.  Probe it only when the
    # downloaded Proposal itself declares V3.0.  This is an isolated parameter
    # read: no WP,1, movement, relay, learning, or parameter-write command is sent.
    autoproduct_parameter_read_probe: dict[str, Any] | None = None
    if str(proposal_info.get("uart_version") or "").strip().upper() == "V3.0":
        autoproduct_parameter_read_probe = await async_probe_parameter_read(
            endpoint=str(entry.data.get(CONF_ENDPOINT) or ""),
            uuid=str(entry.data.get(CONF_UUID) or ""),
            certificate_pem=str(entry.data.get(CONF_CERTIFICATE_PEM) or ""),
            private_key=str(entry.data.get(CONF_PRIVATE_KEY) or ""),
        )

    # Unknown/unmapped controllers get one exhaustive read-only discovery
    # matrix. This replaces repeated bespoke test builds: the resulting single
    # diagnostics JSON records which legacy, UART V3, WBT status and parameter
    # request dialects respond and captures the sanitized payload shapes.
    discovery_required = _needs_controller_discovery(hub)
    unknown_controller_read_matrix: dict[str, Any] | None = None
    if discovery_required:
        existing_wbt_results = {"RS": status_read_probe}
        if autoproduct_parameter_read_probe is not None:
            existing_wbt_results["RP,1"] = autoproduct_parameter_read_probe
        unknown_controller_read_matrix = await async_probe_wbt_read_matrix(
            endpoint=str(entry.data.get(CONF_ENDPOINT) or ""),
            uuid=str(entry.data.get(CONF_UUID) or ""),
            certificate_pem=str(entry.data.get(CONF_CERTIFICATE_PEM) or ""),
            private_key=str(entry.data.get(CONF_PRIVATE_KEY) or ""),
            existing_results=existing_wbt_results,
        )

    ouranos_read_matrix: dict[str, Any] | None = None
    if discovery_required:
        ouranos_read_matrix = await _async_probe_ouranos_read_matrix(
            hass,
            uuid=str(entry.data.get(CONF_UUID) or ""),
            uuid_type=entry.data.get(CONF_UUID_TYPE),
            pin_code=str(entry.options.get(CONF_OURANOS_PIN) or "").strip(),
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
    is_ps22087b_profile = hub.parameter_model_type == PS22087B
    is_ps25142_profile = hub.parameter_model_type == PS25142
    profile = (
        (PS21050D_UART_VERSION, (), "ps21050_app_wire20", "")
        if hub.parameter_model_type == PS21050D
        else (1, (), "ps22087b_p710u_wire15", "")
        if is_ps22087b_profile
        else (1, (), "ps25142_proposal_b_wire18", "")
        if is_ps25142_profile
        else protocol_profile_for(hub.parameter_model_type)
    )
    schema = hub.model_parameter_schema
    last_response_debug = _inspect_parameter_payload(
        hub.attributes.get(ATTR_LAST_RESPONSE)
    )
    shadow_parameter_debug = _inspect_parameter_payload(
        hub.attributes.get(ATTR_DEV_PARAM)
    )
    expected_wire_tokens = (
        len(PS22087B_PARAMETERS)
        if is_ps22087b_profile
        else PS25142_PARAMETER_COUNT
        if is_ps25142_profile
        else _expected_wire_token_count(schema, profile)
    )
    pedestrian_strategy = hub.pedestrian_strategy
    direct_blocked = direct_ped_open_blocked(
        hub.controller_type
    ) or direct_ped_open_blocked(hub.configured_controller_type)

    controller_route_analysis = _controller_route_analysis(
        hub=hub,
        uuid_type=entry.data.get(CONF_UUID_TYPE),
        proposal_info=proposal_info,
        shadow_probe=shadow_get_probe,
        status_probe=status_read_probe,
        parameter_probe=autoproduct_parameter_read_probe,
        wbt_matrix=unknown_controller_read_matrix,
        ouranos_matrix=ouranos_read_matrix,
    )

    return {
        "entry": async_redact_data(dict(entry.data), _REDACT),
        "options": async_redact_data(dict(entry.options), _REDACT),
        "runtime": {
            "available": hub.available,
            "mqtt_connected": hub.mqtt_connected,
            "uuid_type": entry.data.get(CONF_UUID_TYPE),
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
            "ps25142_movement_test_last_result": (
                ouranos_poller.last_movement_test
                if ouranos_poller is not None
                else None
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
            "status_read_probe_observed_payload_count": status_read_probe[
                "observed_payload_count"
            ],
            "status_read_probe_observed_payloads": status_read_probe[
                "observed_payloads"
            ],
            "status_read_probe_error": status_read_probe["probe_error"],
            "autoproduct_parameter_read_probe": autoproduct_parameter_read_probe,
            "unknown_controller_read_matrix": unknown_controller_read_matrix,
            "ouranos_read_matrix": ouranos_read_matrix,
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
            "pedestrian_strategy_reason": (
                "authenticated_ps25007a_live_alias"
                if pedestrian_strategy
                != pedestrian_strategy_for(
                    hub.controller_type, hub.controller_capabilities
                )
                else pedestrian_strategy_reason(
                    hub.controller_type,
                    hub.controller_capabilities,
                )
            ),
            "pedestrian_direct_command_blocked": direct_blocked,
            "pedestrian_relay4_enabled": pedestrian_strategy == PEDESTRIAN_STRATEGY_RELAY4,
            "proposal_id": entry.data.get(CONF_PROPOSAL_ID),
            "proposal_fetch_status": entry.data.get(CONF_PROPOSAL_FETCH_STATUS),
            "proposal_summary": proposal_info,
            "proposal_payload": (
                redact_proposal_payload(proposal) if proposal is not None else None
            ),
            "controller_route_analysis": controller_route_analysis,
            # FunctionSet is authoritative evidence from the vendor AutoProduct
            # profile.  Do not turn it into live commands yet; this beta only
            # captures and exposes the profile so hardware behavior can be
            # verified before command/parameter enablement.
            "function_set_evidence_available": bool(
                proposal_info.get("function_set_available")
            ),
            "function_set_pedestrian": proposal_info.get(
                "pedestrian_function_present"
            ),
            "relay4_available": proposal_info.get("relay4_present"),
            "relay4_function_name": relay4_label,
            "product_type": hub.product_type,
            "parameter_model_type": hub.parameter_model_type,
            "parameter_model_source": hub.parameter_model_source,
            "model_parameter_schema_available": (
                schema is not None or is_ps25142_profile
            ),
            "model_parameter_schema_count": (
                PS25142_PARAMETER_COUNT
                if is_ps25142_profile
                else len(schema or ())
            ),
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
            "model_parameter_schema": _diagnostic_schema(
                hub,
                schema,
                is_ps21050d_alias=is_ps21050d_alias,
                is_ps22027_profile=is_ps22027_profile,
            ),
            "parameters": hub.parameters,
            "attributes": hub.attributes,
        },
    }
