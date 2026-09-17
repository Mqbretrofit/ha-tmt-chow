"""Read-only request-matrix coverage for unknown controllers."""

from __future__ import annotations

import asyncio

from custom_components.tmt_chow.status_diagnostics import (
    async_probe_wbt_read_matrix,
    classify_wbt_response,
)


class _FakeClient:
    published: list[str] = []

    def __init__(self, *, topics, message_callback, **kwargs):
        self._topic = topics[0]
        self._message_callback = message_callback

    async def async_start(self) -> None:
        return

    async def async_publish(self, topic: str, payload: str) -> None:
        self.published.append(payload)
        command = payload.removeprefix("c=")
        response = {
            "RS": "ACK RS:0,0,0,0",
            "READ STATUS": "NAK READ STATUS;src=P1234567",
            "RP,1": "ACK RP,1:1,2,3",
            "READ FUNCTION": "ACK READ FUNCTION,1:1,2:2",
        }[command]
        await self._message_callback(self._topic, response)

    async def async_stop(self) -> None:
        return


def test_classify_wbt_response_keeps_nak_as_evidence() -> None:
    assert classify_wbt_response("ACK RS:0,0,0,0") == "acknowledged"
    assert classify_wbt_response("NAK READ STATUS;src=P1234567") == "rejected"
    assert classify_wbt_response("NAK RS") == "rejected"
    assert classify_wbt_response('{"wbt":"noise"}') == "traffic_observed"
    assert classify_wbt_response(None) == "no_response"


def test_unknown_controller_matrix_uses_only_allowlisted_reads() -> None:
    _FakeClient.published = []
    result = asyncio.run(
        async_probe_wbt_read_matrix(
            endpoint="example.iot",
            uuid="12345678901234567890",
            certificate_pem="cert",
            private_key="key",
            mqtt_client_factory=_FakeClient,
        )
    )
    assert _FakeClient.published == [
        "c=RS",
        "c=READ STATUS",
        "c=RP,1",
        "c=READ FUNCTION",
    ]
    assert result["working_commands"] == [
        "RS",
        "RP,1",
        "READ FUNCTION",
    ]
    assert result["rejected_commands"] == ["READ STATUS"]
    assert result["unresolved_commands"] == []
    assert result["results"]["READ STATUS"]["result"] == "rejected"
    assert result["results"]["RS"]["result"] == "acknowledged"
    assert result["safety"] == {
        "read_only": True,
        "commands_sent_once": True,
        "commands_sent_serially": True,
        "movement_commands_sent": False,
        "parameter_writes_sent": False,
        "relay_learning_or_reset_sent": False,
    }


def test_unknown_controller_matrix_runs_dialects_one_after_another() -> None:
    class _SerialClient(_FakeClient):
        active = 0
        max_active = 0

        async def async_start(self) -> None:
            type(self).active += 1
            type(self).max_active = max(type(self).max_active, type(self).active)

        async def async_stop(self) -> None:
            type(self).active -= 1

    _SerialClient.published = []
    _SerialClient.active = 0
    _SerialClient.max_active = 0
    asyncio.run(
        async_probe_wbt_read_matrix(
            endpoint="example.iot",
            uuid="12345678901234567890",
            certificate_pem="cert",
            private_key="key",
            mqtt_client_factory=_SerialClient,
        )
    )
    assert _SerialClient.max_active == 1
    assert _SerialClient.published == [
        "c=RS",
        "c=READ STATUS",
        "c=RP,1",
        "c=READ FUNCTION",
    ]
