"""Read-only request-matrix coverage for unknown controllers."""

from __future__ import annotations

import asyncio

from custom_components.tmt_chow.status_diagnostics import (
    async_probe_wbt_read_matrix,
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
        "READ STATUS",
        "RP,1",
        "READ FUNCTION",
    ]
    assert result["safety"] == {
        "read_only": True,
        "commands_sent_once": True,
        "movement_commands_sent": False,
        "parameter_writes_sent": False,
        "relay_learning_or_reset_sent": False,
    }
