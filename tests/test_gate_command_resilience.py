"""Regression tests for gate state handling and movement commands."""

from __future__ import annotations

import asyncio

from custom_components.tmt_chow.controller_types import (
    CAPABILITY_PEDESTRIAN,
    controller_capabilities,
)
from custom_components.tmt_chow.hub import TmtChowHub, TmtCommandError
from custom_components.tmt_chow.protocol import GateStatus


def _hub(device_type: str = "PS21053C") -> TmtChowHub:
    return TmtChowHub(
        uuid="test-uuid",
        thing_name="test-thing",
        name="Test gate",
        endpoint="example.invalid",
        certificate_pem="",
        private_key="",
        source_tag="P9999999",
        product_type="112",
        device_type=device_type,
    )


def test_stale_stop_status_cannot_reopen_a_just_closed_gate() -> None:
    hub = _hub()
    hub.position = 0
    hub.movement = "closing"
    hub.is_operating = True

    hub._apply_status(
        GateStatus(
            position=100,
            is_operating=False,
            is_open_direction=False,
            battery_percent=90,
        )
    )

    assert hub.position == 0
    assert hub.is_operating is False
    assert hub.movement is None


def test_stale_stop_status_cannot_close_a_just_opened_gate() -> None:
    hub = _hub()
    hub.position = 100
    hub.movement = "opening"
    hub.is_operating = True

    hub._apply_status(
        GateStatus(
            position=0,
            is_operating=False,
            is_open_direction=True,
            battery_percent=90,
        )
    )

    assert hub.position == 100
    assert hub.is_operating is False
    assert hub.movement is None


def test_stop_mid_travel_can_still_accept_reported_position() -> None:
    hub = _hub()
    hub.position = 40
    hub.movement = None
    hub.is_operating = False

    hub._apply_status(
        GateStatus(
            position=35,
            is_operating=False,
            is_open_direction=False,
            battery_percent=90,
        )
    )

    assert hub.position == 35


def test_fresh_live_position_confirms_missing_open_ack() -> None:
    hub = _hub()
    hub.position = 40
    hub._last_live_position_monotonic = 20.0

    assert hub._motion_confirms_command(
        "opening",
        start_position=0,
        start_operating=False,
        command_started=10.0,
    )


def test_stale_position_does_not_confirm_missing_ack() -> None:
    hub = _hub()
    hub.position = 40
    hub._last_live_position_monotonic = 5.0

    assert not hub._motion_confirms_command(
        "opening",
        start_position=0,
        start_operating=False,
        command_started=10.0,
    )


def test_already_moving_gate_never_uses_ack_fallback() -> None:
    hub = _hub()
    hub.position = 40
    hub.is_operating = True
    hub.movement = "opening"
    hub._last_operating_status_monotonic = 20.0

    assert not hub._motion_confirms_command(
        "opening",
        start_position=20,
        start_operating=True,
        command_started=10.0,
    )


def test_timeout_is_accepted_without_resending_when_motion_is_proven() -> None:
    hub = _hub()
    hub.position = 0
    hub.is_operating = False
    calls = 0

    async def fake_exchange(payload: str, expected: str) -> str:
        nonlocal calls
        calls += 1
        hub.position = 40
        hub._last_live_position_monotonic = 9999999999.0
        try:
            raise TimeoutError
        except TimeoutError as err:
            raise TmtCommandError(
                f"No {expected} acknowledgement",
                translation_key="no_acknowledgement",
                translation_placeholders={"acknowledgement": expected},
            ) from err

    hub._async_exchange = fake_exchange  # type: ignore[method-assign]

    acknowledged = asyncio.run(
        hub._async_command(
            "FULL OPEN",
            "ACK FULL OPEN",
            motion_direction="opening",
        )
    )

    assert acknowledged is False
    assert calls == 1


def test_pedestrian_command_uses_verified_wire_command() -> None:
    hub = _hub()
    captured: list[tuple[str, str, str | None]] = []

    async def fake_command(
        command: str,
        acknowledgement: str,
        *,
        motion_direction: str | None = None,
    ) -> bool:
        captured.append((command, acknowledgement, motion_direction))
        return True

    hub._async_command = fake_command  # type: ignore[method-assign]
    asyncio.run(hub.async_pedestrian_open())

    assert captured == [("PED OPEN", "ACK PED OPEN", "opening")]


def test_pedestrian_capability_is_model_gated() -> None:
    assert CAPABILITY_PEDESTRIAN in controller_capabilities("PS21053C")
    assert CAPABILITY_PEDESTRIAN not in controller_capabilities("PS22087")
