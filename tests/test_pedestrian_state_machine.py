"""Regression tests for pedestrian/partial-opening presentation state."""

from __future__ import annotations

import asyncio
import time

import pytest

from custom_components.tmt_chow.pedestrian_state import (
    async_pedestrian_open_with_display,
    begin_pedestrian_display_cycle,
    cancel_pedestrian_display_cycle,
    pedestrian_display_is_closed,
    pedestrian_display_movement,
    pedestrian_display_phase,
    pedestrian_display_position,
    pedestrian_open_duration_seconds,
    process_pedestrian_display_telemetry,
)
from custom_components.tmt_chow.ps25007a_hub import TmtChowHub


def _hub(device_type: str = "PS21053C") -> TmtChowHub:
    hub = TmtChowHub(
        uuid="test-uuid",
        thing_name="test-thing",
        name="Test gate",
        endpoint="example.invalid",
        certificate_pem="",
        private_key="",
        source_tag="P00317D9",
        product_type="112",
        device_type=device_type,
    )
    hub.position = 0
    hub.is_operating = False
    return hub


def _set_pedestrian_raw_value(hub: TmtChowHub, raw_value: int) -> None:
    schema = hub.model_parameter_schema
    assert schema is not None
    values = [0] * len(schema)
    index = next(
        index
        for index, spec in enumerate(schema)
        if spec[1] in {"pedestrian_mode", "func_pedestrian_mode"}
    )
    values[index] = raw_value
    hub.parameters = tuple(values)


def test_ps21053c_reads_configured_pedestrian_seconds() -> None:
    hub = _hub("PS21053C")
    _set_pedestrian_raw_value(hub, 1)
    assert pedestrian_open_duration_seconds(hub) == 6.0


def test_ps21053c_legacy_select_semantics_still_return_six_seconds() -> None:
    hub = _hub("PS21053C")
    values = [0] * 17
    values[7] = 1
    hub.parameters = tuple(values)
    assert pedestrian_open_duration_seconds(hub) == 6.0


def test_percentage_based_pedestrian_mode_is_not_treated_as_timer() -> None:
    hub = _hub("PS23065")
    _set_pedestrian_raw_value(hub, 1)
    assert pedestrian_open_duration_seconds(hub) is None


def test_shared_wrapper_arms_display_before_command_runs() -> None:
    hub = _hub("PS21053C")
    values = [0] * 17
    values[7] = 1
    hub.parameters = tuple(values)

    async def fake_pedestrian_open() -> None:
        assert pedestrian_display_phase(hub) == "opening"
        assert pedestrian_display_movement(hub) == "opening"
        assert pedestrian_display_is_closed(hub) is False

    hub.async_pedestrian_open = fake_pedestrian_open  # type: ignore[method-assign]

    async def run_test() -> None:
        await async_pedestrian_open_with_display(hub)
        assert pedestrian_display_phase(hub) == "opening"
        cancel_pedestrian_display_cycle(hub, notify=False)

    asyncio.run(run_test())


def test_shared_wrapper_clears_overlay_when_command_fails() -> None:
    hub = _hub("PS21053C")
    values = [0] * 17
    values[7] = 1
    hub.parameters = tuple(values)

    async def fake_pedestrian_open() -> None:
        assert pedestrian_display_phase(hub) == "opening"
        raise RuntimeError("test failure")

    hub.async_pedestrian_open = fake_pedestrian_open  # type: ignore[method-assign]

    async def run_test() -> None:
        with pytest.raises(RuntimeError, match="test failure"):
            await async_pedestrian_open_with_display(hub)
        assert pedestrian_display_phase(hub) is None

    asyncio.run(run_test())


def test_opening_overlay_wins_over_contradictory_raw_closed_state() -> None:
    hub = _hub("PS21053C")
    _set_pedestrian_raw_value(hub, 1)

    async def run_test() -> None:
        assert begin_pedestrian_display_cycle(hub) is True
        hub.position = 0
        hub.is_operating = False
        hub.movement = None
        process_pedestrian_display_telemetry(hub)
        assert pedestrian_display_phase(hub) == "opening"
        assert pedestrian_display_movement(hub) == "opening"
        assert pedestrian_display_is_closed(hub) is False
        assert pedestrian_display_position(hub) is None
        cancel_pedestrian_display_cycle(hub, notify=False)

    asyncio.run(run_test())


def test_reverse_live_position_before_deadline_cannot_change_opening_state() -> None:
    hub = _hub("PS21053C")
    _set_pedestrian_raw_value(hub, 1)

    async def run_test() -> None:
        assert begin_pedestrian_display_cycle(hub) is True

        hub.position = 40
        hub._last_live_position_monotonic = time.monotonic()
        process_pedestrian_display_telemetry(hub)
        assert pedestrian_display_phase(hub) == "opening"
        assert pedestrian_display_position(hub) == 40

        hub.position = 0
        hub._last_live_position_monotonic = time.monotonic() + 1
        process_pedestrian_display_telemetry(hub)
        assert pedestrian_display_phase(hub) == "opening"
        assert pedestrian_display_movement(hub) == "opening"
        assert pedestrian_display_is_closed(hub) is False
        assert pedestrian_display_position(hub) == 40

        hub.position = 30
        hub._last_live_position_monotonic = time.monotonic() + 2
        process_pedestrian_display_telemetry(hub)
        assert pedestrian_display_phase(hub) == "opening"
        assert pedestrian_display_movement(hub) == "opening"
        assert pedestrian_display_position(hub) == 40

        cancel_pedestrian_display_cycle(hub, notify=False)

    asyncio.run(run_test())


def test_timer_boundary_releases_opening_to_partial_open_state() -> None:
    hub = _hub("PS21053C")
    _set_pedestrian_raw_value(hub, 1)

    async def run_test() -> None:
        assert begin_pedestrian_display_cycle(hub) is True
        hub.position = 40
        hub._last_live_position_monotonic = time.monotonic()
        process_pedestrian_display_telemetry(hub)

        hub._tmt_pedestrian_display_deadline = time.monotonic() - 1
        process_pedestrian_display_telemetry(hub)
        assert pedestrian_display_phase(hub) == "open"
        assert pedestrian_display_movement(hub) is None
        assert pedestrian_display_is_closed(hub) is False
        assert pedestrian_display_position(hub) == 40
        cancel_pedestrian_display_cycle(hub, notify=False)

    asyncio.run(run_test())


def test_fresh_closing_status_after_timer_changes_display_to_closing() -> None:
    hub = _hub("PS21053C")
    _set_pedestrian_raw_value(hub, 1)

    async def run_test() -> None:
        assert begin_pedestrian_display_cycle(hub) is True
        hub._tmt_pedestrian_display_deadline = time.monotonic() - 1
        process_pedestrian_display_telemetry(hub)
        assert pedestrian_display_phase(hub) == "open"

        hub.is_operating = True
        hub.movement = "closing"
        hub._last_operating_status_monotonic = time.monotonic()
        process_pedestrian_display_telemetry(hub)
        assert pedestrian_display_phase(hub) == "closing"
        assert pedestrian_display_movement(hub) == "closing"
        cancel_pedestrian_display_cycle(hub, notify=False)

    asyncio.run(run_test())


def test_fresh_live_reverse_after_timer_changes_display_to_closing() -> None:
    hub = _hub("PS21053C")
    _set_pedestrian_raw_value(hub, 1)

    async def run_test() -> None:
        assert begin_pedestrian_display_cycle(hub) is True

        hub.position = 40
        hub._last_live_position_monotonic = time.monotonic()
        process_pedestrian_display_telemetry(hub)
        assert pedestrian_display_phase(hub) == "opening"

        hub._tmt_pedestrian_display_deadline = time.monotonic() - 1
        process_pedestrian_display_telemetry(hub)
        assert pedestrian_display_phase(hub) == "open"

        hub.position = 30
        hub._last_live_position_monotonic = time.monotonic() + 1
        process_pedestrian_display_telemetry(hub)
        assert pedestrian_display_phase(hub) == "closing"
        assert pedestrian_display_movement(hub) == "closing"

        hub.position = 0
        hub.is_operating = False
        hub.movement = None
        hub._last_live_position_monotonic = time.monotonic() + 2
        process_pedestrian_display_telemetry(hub)
        assert pedestrian_display_phase(hub) is None
        assert pedestrian_display_is_closed(hub) is True

    asyncio.run(run_test())


def test_stale_stopped_zero_does_not_end_cycle_after_live_position_was_seen() -> None:
    hub = _hub("PS21053C")
    _set_pedestrian_raw_value(hub, 1)

    async def run_test() -> None:
        assert begin_pedestrian_display_cycle(hub) is True

        hub.position = 40
        hub._last_live_position_monotonic = time.monotonic()
        process_pedestrian_display_telemetry(hub)
        hub._tmt_pedestrian_display_deadline = time.monotonic() - 1
        process_pedestrian_display_telemetry(hub)

        hub.is_operating = True
        hub.movement = "closing"
        hub._last_operating_status_monotonic = time.monotonic() + 1
        process_pedestrian_display_telemetry(hub)
        assert pedestrian_display_phase(hub) == "closing"

        hub.position = 0
        hub.is_operating = False
        hub.movement = None
        process_pedestrian_display_telemetry(hub)
        assert pedestrian_display_phase(hub) == "closing"
        assert pedestrian_display_is_closed(hub) is False

        cancel_pedestrian_display_cycle(hub, notify=False)

    asyncio.run(run_test())
