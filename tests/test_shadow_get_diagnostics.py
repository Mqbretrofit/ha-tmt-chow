"""Regression tests for read-only AWS Shadow GET diagnostics."""

from __future__ import annotations

import asyncio
from typing import Any

from custom_components.tmt_chow.shadow_diagnostics import async_probe_shadow_get


class _FakeMqttClient:
    response_topic_suffix = "/accepted"
    response_payload = "{}"
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
        if self.response_topic_suffix:
            await self._message_callback(
                f"{topic}{self.response_topic_suffix}",
                self.response_payload,
            )

    async def async_stop(self) -> None:
        return


def _run_probe(factory: type[_FakeMqttClient], **kwargs: Any) -> dict[str, Any]:
    factory.publish_calls = []
    factory.topics = ()
    return asyncio.run(
        async_probe_shadow_get(
            endpoint="iot.example.invalid",
            uuid="ps19001-test-uuid",
            thing_name="ps19001-test-uuid",
            certificate_pem="CERT",
            private_key="KEY",
            response_timeout=0.01,
            mqtt_client_factory=factory,
            **kwargs,
        )
    )


def test_shadow_probe_subscribes_only_to_get_responses_and_publishes_get() -> None:
    class AcceptedClient(_FakeMqttClient):
        response_topic_suffix = "/accepted"
        response_payload = '{"state":{"reported":{}}}'

    result = _run_probe(AcceptedClient)

    assert result == {
        "result": "accepted",
        "rejection_code": None,
        "rejection_message": None,
        "probe_error": None,
    }
    assert AcceptedClient.topics == (
        "$aws/things/ps19001-test-uuid/shadow/get/accepted",
        "$aws/things/ps19001-test-uuid/shadow/get/rejected",
    )
    assert AcceptedClient.publish_calls == [
        ("$aws/things/ps19001-test-uuid/shadow/get", "{}")
    ]
    assert all("wbt01" not in topic for topic in AcceptedClient.topics)


def test_shadow_probe_reports_rejection_and_redacts_identifier() -> None:
    class RejectedClient(_FakeMqttClient):
        response_topic_suffix = "/rejected"
        response_payload = (
            '{"code":404,"message":"No shadow for ps19001-test-uuid"}'
        )

    result = _run_probe(RejectedClient)

    assert result["result"] == "rejected"
    assert result["rejection_code"] == 404
    assert result["rejection_message"] == "No shadow for <redacted>"
    assert "ps19001-test-uuid" not in result["rejection_message"]


def test_shadow_probe_reports_no_response_without_sending_gate_command() -> None:
    class SilentClient(_FakeMqttClient):
        response_topic_suffix = ""

    result = _run_probe(SilentClient)

    assert result["result"] == "no_response"
    assert result["probe_error"] is None
    assert SilentClient.publish_calls == [
        ("$aws/things/ps19001-test-uuid/shadow/get", "{}")
    ]
