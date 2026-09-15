"""Regression tests for the read-only WBT status diagnostic probe."""

from __future__ import annotations

import asyncio
from typing import Any

from custom_components.tmt_chow.status_diagnostics import async_probe_status_read


class _FakeMqttClient:
    response_payload = "ACK RS:20,5E,A2,01,40,00,FF,FF,FF"
    publish_calls: list[tuple[str, str]] = []
    topics: tuple[str, ...] = ()

    def __init__(
        self,
        *,
        endpoint: str,
        client_id: str,
        certificate_pem: str,
        private_key: str,
        topics: tuple[str, ...],
        message_callback,
        state_callback,
    ) -> None:
        del endpoint, client_id, certificate_pem, private_key, state_callback
        type(self).topics = topics
        self._message_callback = message_callback

    async def async_start(self) -> None:
        return

    async def async_publish(self, topic: str, payload: str) -> None:
        type(self).publish_calls.append((topic, payload))
        if self.response_payload is not None:
            await self._message_callback(
                "ps19001-test-uuid/wbt01Tx",
                self.response_payload,
            )

    async def async_stop(self) -> None:
        return


def _run_probe(factory: type[_FakeMqttClient], **kwargs: Any) -> dict[str, Any]:
    factory.publish_calls = []
    factory.topics = ()
    return asyncio.run(
        async_probe_status_read(
            endpoint="iot.example.invalid",
            uuid="ps19001-test-uuid",
            certificate_pem="CERT",
            private_key="KEY",
            response_timeout=0.01,
            mqtt_client_factory=factory,
            **kwargs,
        )
    )


def test_status_probe_subscribes_only_to_tx_and_publishes_one_rs_read() -> None:
    class StatusClient(_FakeMqttClient):
        response_payload = "ACK RS:20,5E,A2,01,40,00,FF,FF,FF"

    result = _run_probe(StatusClient)

    assert StatusClient.topics == ("ps19001-test-uuid/wbt01Tx",)
    assert StatusClient.publish_calls == [("ps19001-test-uuid/wbt01Rx", "c=RS")]
    assert result == {
        "result": "acknowledged",
        "ack": "ACK RS:20,5E,A2,01,40,00,FF,FF,FF",
        "parsed": True,
        "position": 1,
        "is_operating": False,
        "open_direction": False,
        "battery_percent": 94,
        "probe_error": None,
    }


def test_status_probe_ignores_unrelated_wbt_payload() -> None:
    class UnrelatedClient(_FakeMqttClient):
        response_payload = "ACK READ FUNCTION:1,2,3"

    result = _run_probe(UnrelatedClient)

    assert result["result"] == "no_response"
    assert result["ack"] is None
    assert result["probe_error"] is None
    assert UnrelatedClient.publish_calls == [
        ("ps19001-test-uuid/wbt01Rx", "c=RS")
    ]


def test_status_probe_never_sends_movement_or_parameter_write_commands() -> None:
    class SilentClient(_FakeMqttClient):
        response_payload = None

    result = _run_probe(SilentClient)

    assert result["result"] == "no_response"
    assert SilentClient.publish_calls == [
        ("ps19001-test-uuid/wbt01Rx", "c=RS")
    ]
    published_payloads = [payload for _, payload in SilentClient.publish_calls]
    forbidden = ("FULL OPEN", "FULL CLOSE", "PED OPEN", "STOP", "WP,", "WRITE FUNCTION")
    assert not any(token in payload for payload in published_payloads for token in forbidden)
