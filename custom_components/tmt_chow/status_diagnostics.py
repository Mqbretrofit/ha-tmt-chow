"""Read-only WBT status diagnostics for TMT Chow."""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import Any, Callable

from .mqtt import AsyncMqttClient, MqttError
from .protocol import parse_ack_rs

STATUS_READ_RESPONSE_TIMEOUT = 5.0
STATUS_PROBE_CONNECT_TIMEOUT = 20.0


def _format_exception(err: BaseException) -> str:
    message = str(err).strip()
    return f"{type(err).__name__}: {message}" if message else type(err).__name__


async def async_probe_status_read(
    *,
    endpoint: str,
    uuid: str,
    certificate_pem: str,
    private_key: str,
    response_timeout: float = STATUS_READ_RESPONSE_TIMEOUT,
    mqtt_client_factory: Callable[..., AsyncMqttClient] = AsyncMqttClient,
) -> dict[str, Any]:
    """Issue one isolated read-only ``c=RS`` request and classify its response.

    The diagnostic connection subscribes only to the device's WBT transmit topic
    and publishes exactly one status-read request to its WBT receive topic. It
    never sends movement commands or parameter writes.
    """
    result: dict[str, Any] = {
        "result": "no_response",
        "ack": None,
        "parsed": False,
        "position": None,
        "is_operating": None,
        "open_direction": None,
        "battery_percent": None,
        "probe_error": None,
    }
    if not all((endpoint, uuid, certificate_pem, private_key)):
        result["probe_error"] = "missing_aws_credentials"
        return result

    rx_topic = f"{uuid}/wbt01Rx"
    tx_topic = f"{uuid}/wbt01Tx"
    loop = asyncio.get_running_loop()
    response: asyncio.Future[str] = loop.create_future()

    async def _message_callback(topic: str, payload: str) -> None:
        if response.done():
            return
        if topic == tx_topic and payload.startswith("ACK RS:"):
            response.set_result(payload)

    def _state_callback(_connected: bool) -> None:
        return

    suffix = f"{time.monotonic_ns() & 0xFFFFFF:06x}"
    client = mqtt_client_factory(
        endpoint=endpoint,
        client_id=f"ha-status-diag-{uuid[-12:]}-{suffix}",
        certificate_pem=certificate_pem,
        private_key=private_key,
        topics=(tx_topic,),
        message_callback=_message_callback,
        state_callback=_state_callback,
    )

    try:
        await asyncio.wait_for(client.async_start(), timeout=STATUS_PROBE_CONNECT_TIMEOUT)
        await client.async_publish(rx_topic, "c=RS")
        try:
            payload = await asyncio.wait_for(response, timeout=response_timeout)
        except TimeoutError:
            return result

        result["result"] = "acknowledged"
        result["ack"] = payload
        status = parse_ack_rs(payload)
        if status is not None:
            result["parsed"] = True
            result["position"] = status.position
            result["is_operating"] = status.is_operating
            result["open_direction"] = status.is_open_direction
            result["battery_percent"] = status.battery_percent
        return result
    except (MqttError, TimeoutError) as err:
        result["probe_error"] = _format_exception(err)
        return result
    finally:
        with contextlib.suppress(Exception):
            await client.async_stop()
