"""Read-only AWS IoT Shadow diagnostics for TMT Chow."""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from typing import Any, Callable

from .mqtt import AsyncMqttClient, MqttError

SHADOW_GET_RESPONSE_TIMEOUT = 5.0
SHADOW_PROBE_CONNECT_TIMEOUT = 20.0


def _format_exception(err: BaseException) -> str:
    message = str(err).strip()
    return f"{type(err).__name__}: {message}" if message else type(err).__name__


def _redact_sensitive_text(value: Any, sensitive_values: tuple[str, ...]) -> str | None:
    if not isinstance(value, str):
        return None
    redacted = value
    for sensitive in sensitive_values:
        if sensitive:
            redacted = redacted.replace(sensitive, "<redacted>")
    return redacted


def _parse_rejection(
    payload: str,
    *,
    sensitive_values: tuple[str, ...],
) -> tuple[Any, str | None]:
    try:
        document = json.loads(payload)
    except (TypeError, ValueError):
        return None, None
    if not isinstance(document, dict):
        return None, None
    return (
        document.get("code"),
        _redact_sensitive_text(document.get("message"), sensitive_values),
    )


async def async_probe_shadow_get(
    *,
    endpoint: str,
    uuid: str,
    thing_name: str,
    certificate_pem: str,
    private_key: str,
    response_timeout: float = SHADOW_GET_RESPONSE_TIMEOUT,
    mqtt_client_factory: Callable[..., AsyncMqttClient] = AsyncMqttClient,
) -> dict[str, Any]:
    """Issue one isolated read-only Shadow GET and classify its response.

    This diagnostic connection subscribes only to the classic Shadow GET
    accepted/rejected response topics and publishes only an empty Shadow GET.
    It never subscribes to or publishes gate command topics.
    """
    result: dict[str, Any] = {
        "result": "no_response",
        "rejection_code": None,
        "rejection_message": None,
        "probe_error": None,
    }
    if not all((endpoint, uuid, certificate_pem, private_key)):
        result["probe_error"] = "missing_aws_credentials"
        return result

    shadow_get_topic = f"$aws/things/{uuid}/shadow/get"
    accepted_topic = f"{shadow_get_topic}/accepted"
    rejected_topic = f"{shadow_get_topic}/rejected"
    loop = asyncio.get_running_loop()
    response: asyncio.Future[tuple[str, str]] = loop.create_future()

    async def _message_callback(topic: str, payload: str) -> None:
        if response.done():
            return
        if topic == accepted_topic:
            response.set_result(("accepted", payload))
        elif topic == rejected_topic:
            response.set_result(("rejected", payload))

    def _state_callback(_connected: bool) -> None:
        return

    suffix = f"{time.monotonic_ns() & 0xFFFFFF:06x}"
    client = mqtt_client_factory(
        endpoint=endpoint,
        client_id=f"ha-diag-{uuid[-12:]}-{suffix}",
        certificate_pem=certificate_pem,
        private_key=private_key,
        topics=(accepted_topic, rejected_topic),
        message_callback=_message_callback,
        state_callback=_state_callback,
    )

    try:
        await asyncio.wait_for(client.async_start(), timeout=SHADOW_PROBE_CONNECT_TIMEOUT)
        await client.async_publish(shadow_get_topic, "{}")
        try:
            outcome, payload = await asyncio.wait_for(
                response,
                timeout=response_timeout,
            )
        except TimeoutError:
            return result

        result["result"] = outcome
        if outcome == "rejected":
            code, message = _parse_rejection(
                payload,
                sensitive_values=(uuid, thing_name, endpoint),
            )
            result["rejection_code"] = code
            result["rejection_message"] = message
        return result
    except (MqttError, TimeoutError) as err:
        result["probe_error"] = _format_exception(err)
        return result
    finally:
        with contextlib.suppress(Exception):
            await client.async_stop()
