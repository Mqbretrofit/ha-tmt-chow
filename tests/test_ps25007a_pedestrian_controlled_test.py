"""Safety tests for the isolated PS25007A PED OPEN experiment."""

from __future__ import annotations

import asyncio

import pytest

from custom_components.tmt_chow.hub import TmtCommandError
from custom_components.tmt_chow.pedestrian import PEDESTRIAN_STRATEGY_NONE
from custom_components.tmt_chow.ps25007a_hub import TmtChowHub

_OBSERVED_VALUES = (1, 3, 0, 3, 3, 3, 11, 1, 1, 1, 0, 2, 3, 0, 0, 0, 0)


def _hub(source_tag: str = "P00317D9") -> TmtChowHub:
    hub = TmtChowHub(
        uuid="test-uuid",
        thing_name="test-thing",
        name="Test gate",
        endpoint="example.invalid",
        certificate_pem="",
        private_key="",
        source_tag=source_tag,
        product_type="112",
        device_type="PS25007",
    )
    hub._set_controller_type("PS25007A")
    hub.position = 0
    hub.is_operating = False
    return hub


def test_normal_ps25007a_pedestrian_strategy_remains_blocked() -> None:
    hub = _hub()
    assert hub.pedestrian_strategy == PEDESTRIAN_STRATEGY_NONE


def test_controlled_test_rejects_anonymous_source_tag() -> None:
    hub = _hub("P9999999")

    with pytest.raises(TmtCommandError, match="non-anonymous"):
        asyncio.run(
            hub.async_ps25007a_pedestrian_test("PED OPEN P9999999")
        )


def test_controlled_test_requires_closed_stopped_gate() -> None:
    hub = _hub()
    hub.position = 40

    with pytest.raises(TmtCommandError, match="fully closed and stopped"):
        asyncio.run(
            hub.async_ps25007a_pedestrian_test("PED OPEN P00317D9")
        )


def test_controlled_test_requires_runtime_source_in_confirmation() -> None:
    hub = _hub()

    with pytest.raises(TmtCommandError, match="Confirmation must be exactly"):
        asyncio.run(
            hub.async_ps25007a_pedestrian_test("PED OPEN P9999999")
        )


def test_controlled_test_sends_one_ped_open_with_identified_source() -> None:
    hub = _hub()
    calls: list[tuple[str, str]] = []
    observed_body = ",".join(map(str, _OBSERVED_VALUES))

    async def fake_exchange(payload: str, expected: str) -> str:
        calls.append((payload, expected))
        if expected == "ACK RP,1":
            return f"ACK RP,1:{observed_body}"
        if expected == "ACK PED OPEN":
            return "ACK PED OPEN"
        raise AssertionError(f"Unexpected exchange: {payload} / {expected}")

    hub._async_exchange = fake_exchange  # type: ignore[method-assign]

    asyncio.run(
        hub.async_ps25007a_pedestrian_test("PED OPEN P00317D9")
    )

    assert calls == [
        ("c=RP,1", "ACK RP,1"),
        ("c=PED OPEN;src=P00317D9", "ACK PED OPEN"),
    ]
    diag = hub.ps25007a_ped_test_diagnostics
    assert diag["normal_pedestrian_strategy"] == PEDESTRIAN_STRATEGY_NONE
    assert diag["ack_received"] is True
    assert diag["telemetry_confirmed_without_ack"] is False
    assert diag["preflight_parameters"] == _OBSERVED_VALUES


def test_controlled_test_records_telemetry_rescue_without_resend() -> None:
    hub = _hub()
    command_calls = 0

    async def fake_refresh() -> None:
        hub.parameters = _OBSERVED_VALUES

    async def fake_command(
        command: str,
        acknowledgement: str,
        *,
        motion_direction: str | None = None,
    ) -> bool:
        nonlocal command_calls
        command_calls += 1
        return False

    hub.async_refresh_parameters = fake_refresh  # type: ignore[method-assign]
    hub._async_command = fake_command  # type: ignore[method-assign]

    asyncio.run(
        hub.async_ps25007a_pedestrian_test("PED OPEN P00317D9")
    )

    assert command_calls == 1
    diag = hub.ps25007a_ped_test_diagnostics
    assert diag["ack_received"] is False
    assert diag["telemetry_confirmed_without_ack"] is True
