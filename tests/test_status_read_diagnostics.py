"""Regression tests for the read-only WBT diagnostic probes."""

from __future__ import annotations

import asyncio
from typing import Any

from custom_components.tmt_chow.status_diagnostics import (
    async_probe_parameter_read,
    async_probe_status_read,
)


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


def _run_status_probe(
    factory: type[_FakeMqttClient], **kwargs: Any
) -> dict[str, Any]:
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


def _run_parameter_probe(factory: type[_FakeMqttClient]) -> dict[str, Any]:
    factory.publish_calls = []
    factory.topics = ()
    return asyncio.run(
        async_probe_parameter_read(
            endpoint="iot.example.invalid",
            uuid="ps19001-test-uuid",
            certificate_pem="CERT",
            private_key="KEY",
            response_timeout=0.01,
            mqtt_client_factory=factory,
        )
    )


def test_status_probe_subscribes_only_to_tx_and_publishes_one_rs_read() -> None:
    class StatusClient(_FakeMqttClient):
        response_payload = "ACK RS:20,5E,A2,01,40,00,FF,FF,FF"

    result = _run_status_probe(StatusClient)

    assert StatusClient.topics == ("ps19001-test-uuid/wbt01Tx",)
    assert StatusClient.publish_calls == [("ps19001-test-uuid/wbt01Rx", "c=RS")]
    assert result == {
        "result": "acknowledged",
        "ack": "ACK RS:20,5E,A2,01,40,00,FF,FF,FF",
        "published_command": "RS",
        "observed_payload_count": 1,
        "observed_payloads": ["ACK RS:20,5E,A2,01,40,00,FF,FF,FF"],
        "probe_error": None,
        "parsed": True,
        "position": 1,
        "is_operating": False,
        "open_direction": False,
        "battery_percent": 94,
    }


def test_status_probe_matches_vendor_contains_behavior_and_parses_json_wrapper() -> None:
    class WrappedStatusClient(_FakeMqttClient):
        response_payload = (
            '{"CMD":"UART","RESULT":0,'
            '"DATA":"prefix ACK RS:20,5E,A2,81,40,00,FF,FF,FF"}'
        )

    result = _run_status_probe(WrappedStatusClient)

    assert result["result"] == "acknowledged"
    assert "ACK RS" in str(result["ack"])
    assert result["parsed"] is True
    assert result["position"] == 1
    assert result["open_direction"] is True


def test_status_probe_records_unrelated_wbt_payload() -> None:
    class UnrelatedClient(_FakeMqttClient):
        response_payload = "ACK READ FUNCTION:1,2,3"

    result = _run_status_probe(UnrelatedClient)

    assert result["result"] == "traffic_observed"
    assert result["ack"] is None
    assert result["observed_payload_count"] == 1
    assert result["observed_payloads"] == ["ACK READ FUNCTION:1,2,3"]
    assert result["probe_error"] is None
    assert UnrelatedClient.publish_calls == [
        ("ps19001-test-uuid/wbt01Rx", "c=RS")
    ]


def test_parameter_probe_sends_only_one_rp1_read() -> None:
    class ParameterClient(_FakeMqttClient):
        response_payload = "ACK RP,1:1,2,3"

    result = _run_parameter_probe(ParameterClient)

    assert ParameterClient.topics == ("ps19001-test-uuid/wbt01Tx",)
    assert ParameterClient.publish_calls == [
        ("ps19001-test-uuid/wbt01Rx", "c=RP,1")
    ]
    assert result["result"] == "acknowledged"
    assert result["ack"] == "ACK RP,1:1,2,3"
    assert result["published_command"] == "RP,1"
    assert result["observed_payloads"] == ["ACK RP,1:1,2,3"]


def test_read_probes_never_send_movement_or_parameter_write_commands() -> None:
    class SilentClient(_FakeMqttClient):
        response_payload = None

    status_result = _run_status_probe(SilentClient)
    status_calls = list(SilentClient.publish_calls)
    parameter_result = _run_parameter_probe(SilentClient)
    parameter_calls = list(SilentClient.publish_calls)

    assert status_result["result"] == "no_response"
    assert parameter_result["result"] == "no_response"
    assert status_calls == [("ps19001-test-uuid/wbt01Rx", "c=RS")]
    assert parameter_calls == [("ps19001-test-uuid/wbt01Rx", "c=RP,1")]
    published_payloads = [payload for _, payload in status_calls + parameter_calls]
    forbidden = (
        "FULL OPEN",
        "FULL CLOSE",
        "PED OPEN",
        "STOP",
        "WP,",
        "WRITE FUNCTION",
        "RELAY",
        "LEARN",
    )
    assert not any(token in payload for payload in published_payloads for token in forbidden)


def test_observed_payloads_redact_common_identifiers() -> None:
    class SensitiveClient(_FakeMqttClient):
        response_payload = (
            "NOTICE uuid=ps19001-test-uuid;ip=192.168.1.20;"
            "mac=AA:BB:CC:DD:EE:FF;ssid=HomeWifi;user=test@example.com"
        )

    result = _run_status_probe(SensitiveClient)

    assert result["result"] == "traffic_observed"
    observed = result["observed_payloads"][0]
    assert "ps19001-test-uuid" not in observed
    assert "192.168.1.20" not in observed
    assert "AA:BB:CC:DD:EE:FF" not in observed
    assert "HomeWifi" not in observed
    assert "test@example.com" not in observed
