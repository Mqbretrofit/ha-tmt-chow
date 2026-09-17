"""Read-only WBT diagnostics for TMT Chow."""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
import time
from typing import Any, Callable

from .mqtt import AsyncMqttClient, MqttError
from .protocol import GateStatus, parse_ack_rs

STATUS_READ_RESPONSE_TIMEOUT = 5.0
PARAMETER_READ_RESPONSE_TIMEOUT = 5.0
STATUS_PROBE_CONNECT_TIMEOUT = 20.0
MAX_OBSERVED_PAYLOADS = 16
MAX_OBSERVED_PAYLOAD_LENGTH = 1024

_EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
_IPV4_RE = re.compile(r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)")
_MAC_RE = re.compile(r"(?i)(?<![0-9a-f])(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}(?![0-9a-f])")
_SSID_RE = re.compile(r"(?i)(ssid\s*[:=]\s*)([^,;\r\n]+)")
_ACK_RS_RE = re.compile(r"ACK RS:[^\"}\r\n]+", re.IGNORECASE)


def _format_exception(err: BaseException) -> str:
    message = str(err).strip()
    return f"{type(err).__name__}: {message}" if message else type(err).__name__


def _sanitize_observed_payload(payload: str, uuid: str) -> str:
    """Keep wire evidence useful while removing common personal identifiers."""
    value = payload
    if uuid:
        value = value.replace(uuid, "<uuid>")
    value = _EMAIL_RE.sub("<email>", value)
    value = _MAC_RE.sub("<mac>", value)
    value = _IPV4_RE.sub("<ip>", value)
    value = _SSID_RE.sub(r"\1<ssid>", value)
    if len(value) > MAX_OBSERVED_PAYLOAD_LENGTH:
        value = value[:MAX_OBSERVED_PAYLOAD_LENGTH] + "…<truncated>"
    return value


def _extract_ack_rs(payload: str | None) -> str | None:
    """Extract an ACK RS frame even when the vendor wraps it in another payload."""
    if not payload:
        return None
    if payload.startswith("ACK RS:"):
        return payload

    # Some native/vendor paths wrap the UART response in JSON.  Search decoded
    # string values first so a suffix such as `"}` is not mistaken for wire data.
    try:
        envelope = json.loads(payload)
    except (TypeError, ValueError):
        envelope = None

    def _walk(value: Any) -> str | None:
        if isinstance(value, str):
            pos = value.upper().find("ACK RS:")
            return value[pos:] if pos >= 0 else None
        if isinstance(value, dict):
            for item in value.values():
                found = _walk(item)
                if found is not None:
                    return found
        if isinstance(value, list):
            for item in value:
                found = _walk(item)
                if found is not None:
                    return found
        return None

    nested = _walk(envelope)
    if nested is not None:
        return nested

    match = _ACK_RS_RE.search(payload)
    return match.group(0).strip() if match else None


def _parse_observed_status(payload: str | None) -> GateStatus | None:
    extracted = _extract_ack_rs(payload)
    return parse_ack_rs(extracted) if extracted is not None else None


async def _async_probe_wbt_read(
    *,
    endpoint: str,
    uuid: str,
    certificate_pem: str,
    private_key: str,
    command: str,
    response_markers: tuple[str, ...],
    response_timeout: float,
    mqtt_client_factory: Callable[..., AsyncMqttClient],
) -> dict[str, Any]:
    """Publish one non-movement read command and capture WBT transmit traffic."""
    result: dict[str, Any] = {
        "result": "no_response",
        "ack": None,
        "published_command": command,
        "observed_payload_count": 0,
        "observed_payloads": [],
        "probe_error": None,
    }
    if not all((endpoint, uuid, certificate_pem, private_key)):
        result["probe_error"] = "missing_aws_credentials"
        return result

    rx_topic = f"{uuid}/wbt01Rx"
    tx_topic = f"{uuid}/wbt01Tx"
    loop = asyncio.get_running_loop()
    response: asyncio.Future[str] = loop.create_future()
    observed_raw: list[str] = []
    marker_folds = tuple(marker.casefold() for marker in response_markers)

    async def _message_callback(topic: str, payload: str) -> None:
        if topic != tx_topic:
            return
        if len(observed_raw) < MAX_OBSERVED_PAYLOADS:
            observed_raw.append(payload)
        if response.done():
            return
        folded = payload.casefold()
        if any(marker in folded for marker in marker_folds):
            response.set_result(payload)

    def _state_callback(_connected: bool) -> None:
        return

    suffix = f"{time.monotonic_ns() & 0xFFFFFF:06x}"
    client = mqtt_client_factory(
        endpoint=endpoint,
        client_id=f"ha-read-diag-{uuid[-12:]}-{suffix}",
        certificate_pem=certificate_pem,
        private_key=private_key,
        topics=(tx_topic,),
        message_callback=_message_callback,
        state_callback=_state_callback,
    )

    try:
        await asyncio.wait_for(client.async_start(), timeout=STATUS_PROBE_CONNECT_TIMEOUT)
        await client.async_publish(rx_topic, f"c={command}")
        try:
            payload = await asyncio.wait_for(response, timeout=response_timeout)
        except TimeoutError:
            result["result"] = "traffic_observed" if observed_raw else "no_response"
        else:
            result["result"] = "acknowledged"
            result["ack"] = _sanitize_observed_payload(payload, uuid)
        return result
    except (MqttError, TimeoutError) as err:
        result["probe_error"] = _format_exception(err)
        return result
    finally:
        result["observed_payload_count"] = len(observed_raw)
        result["observed_payloads"] = [
            _sanitize_observed_payload(payload, uuid) for payload in observed_raw
        ]
        with contextlib.suppress(Exception):
            await client.async_stop()


async def async_probe_status_read(
    *,
    endpoint: str,
    uuid: str,
    certificate_pem: str,
    private_key: str,
    response_timeout: float = STATUS_READ_RESPONSE_TIMEOUT,
    mqtt_client_factory: Callable[..., AsyncMqttClient] = AsyncMqttClient,
) -> dict[str, Any]:
    """Issue one isolated ``c=RS`` read and capture every WBT transmit payload.

    TMT Chow's Android WBT path recognizes status replies using `contains("ACK
    RS")`, while the integration historically required `startswith("ACK RS:")`.
    This diagnostic keeps the normal live parser unchanged but records the raw
    response shape so new controllers can be mapped safely.
    """
    result = await _async_probe_wbt_read(
        endpoint=endpoint,
        uuid=uuid,
        certificate_pem=certificate_pem,
        private_key=private_key,
        command="RS",
        response_markers=("ACK RS",),
        response_timeout=response_timeout,
        mqtt_client_factory=mqtt_client_factory,
    )
    result.update(
        {
            "parsed": False,
            "position": None,
            "is_operating": None,
            "open_direction": None,
            "battery_percent": None,
        }
    )
    raw_ack = result.get("ack")
    status = _parse_observed_status(raw_ack if isinstance(raw_ack, str) else None)
    if status is not None:
        result["parsed"] = True
        result["position"] = status.position
        result["is_operating"] = status.is_operating
        result["open_direction"] = status.is_open_direction
        result["battery_percent"] = status.battery_percent
    return result


async def async_probe_parameter_read(
    *,
    endpoint: str,
    uuid: str,
    certificate_pem: str,
    private_key: str,
    response_timeout: float = PARAMETER_READ_RESPONSE_TIMEOUT,
    mqtt_client_factory: Callable[..., AsyncMqttClient] = AsyncMqttClient,
) -> dict[str, Any]:
    """Issue one isolated AutoProduct UART-V3 ``c=RP,1`` parameter read.

    This is a read-only diagnostic.  It never sends `WP,1`, movement commands,
    learning commands, relay commands, or any parameter write.
    """
    return await _async_probe_wbt_read(
        endpoint=endpoint,
        uuid=uuid,
        certificate_pem=certificate_pem,
        private_key=private_key,
        command="RP,1",
        response_markers=("ACK RP,1", "ACK RP", "ACK READ FUNCTION"),
        response_timeout=response_timeout,
        mqtt_client_factory=mqtt_client_factory,
    )


async def async_probe_wbt_read_matrix(
    *,
    endpoint: str,
    uuid: str,
    certificate_pem: str,
    private_key: str,
    response_timeout: float = 3.0,
    mqtt_client_factory: Callable[..., AsyncMqttClient] = AsyncMqttClient,
    existing_results: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Try every known non-mutating WBT read dialect for an unknown controller.

    Each request uses an isolated connection and is sent exactly once. The
    matrix never sends movement, relay, learning, reset, or write commands.
    """
    probes = (
        ("RS", ("ACK RS", "NAK RS")),
        (
            "READ STATUS",
            ("ACK READ STATUS", "ACK STATUS", "NAK READ STATUS", "NAK STATUS"),
        ),
        ("RP,1", ("ACK RP,1", "ACK RP", "NAK RP")),
        (
            "READ FUNCTION",
            ("ACK READ FUNCTION", "NAK READ FUNCTION"),
        ),
    )
    results: dict[str, Any] = dict(existing_results or {})
    pending = [item for item in probes if item[0] not in results]
    completed = await asyncio.gather(
        *(
            _async_probe_wbt_read(
                endpoint=endpoint,
                uuid=uuid,
                certificate_pem=certificate_pem,
                private_key=private_key,
                command=command,
                response_markers=markers,
                response_timeout=response_timeout,
                mqtt_client_factory=mqtt_client_factory,
            )
            for command, markers in pending
        )
    )
    results.update(
        (command, result)
        for (command, _markers), result in zip(pending, completed, strict=True)
    )
    # Preserve APK command order even when probes completed out of order.
    results = {command: results[command] for command, _markers in probes}
    return {
        "safety": {
            "read_only": True,
            "commands_sent_once": True,
            "movement_commands_sent": False,
            "parameter_writes_sent": False,
            "relay_learning_or_reset_sent": False,
        },
        "apk_command_catalog": {
            "probed_read_only": [command for command, _markers in probes],
            "observed_but_not_automatically_probed": [
                "FULL OPEN",
                "FULL CLOSE",
                "STOP",
                "PED OPEN",
                "EXTERNAL",
                "LIGHT ON",
                "LIGHT OFF",
                "RELAY4",
                "LEARN",
                "WP,1:<model-specific full frame>",
                "WRITE FUNCTION:<model-specific full frame>",
            ],
            "reason_not_probed": "commands may move hardware or change settings",
            "mqtt_publish_topic": f"<uuid>/wbt01Rx",
            "mqtt_observation_topic": f"<uuid>/wbt01Tx",
            "wire_envelope": "c=<command>[;src=<authenticated source tag>]",
        },
        "results": results,
        "working_commands": [
            command
            for command, result in results.items()
            if result.get("result") == "acknowledged"
        ],
    }
