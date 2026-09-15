"""Regression tests for pedestrian/partial-opening presentation state."""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest

from custom_components.tmt_chow.pedestrian_state import (
    async_pedestrian_open_with_display,
    begin_pedestrian_display_cycle,
    cancel_pedestrian_display_cycle,
    pedestrian_auto_close_delay_seconds,
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


def _set_legacy_timers(
    hub: TmtChowHub,
    *,
    pedestrian_raw: int = 1,
    auto_close_raw: int = 3,
) -> None:
    values = [0] * 17
    values[1] = auto_close_raw
    values[7] = pedestrian_raw
    hub.parameters = tuple(values)


def test_ps21053c_reads_configured_pedestrian_seconds() -> None:
    hub = _hub("PS21053C")
    _set_pedestrian_raw_value(hub, 1)
    assert pedestrian_open_duration_seconds(hub) == 6.0


def test_ps21053c_legacy_select_semantics_still_return_six_seconds() -> None:
    hub = _hub("PS21053C")
    _set_legacy_timers(hub)
    assert pedestrian_open_duration_seconds(hub) == 6.0


def test_ps21053c_reads_normal_auto_closing_as_ped_hold_time() -> None:
    hub = _hub("PS21053C")
    _set_legacy_timers(hub, auto_close_raw=3)
    assert pedestrian_auto_close_delay_seconds(hub) == 30.0


def test_ps25007a_uses_same_verified_17_slot_auto_close_timer() -> None:
    hub = _hub("PS25007")
    hub._set_controller_type("PS25007A")
    _set_legacy_timers(hub, auto_close_raw=3)
    assert pedestrian_open_duration_seconds(hub) == 6.0
    assert pedestrian_auto_close_delay_seconds(hub) == 30.0


def test_dedicated_ped_auto_close_overrides_normal_auto_close() -> None:
    # option_auto_closing = OFF,30,60,...; dedicated raw=1 therefore 30 sec,
    # normal raw=2 therefore 60 sec. The dedicated field must win.
    hub = SimpleNamespace(
        controller_type="OTHER",
        configured_controller_type="OTHER",
        parameter_model_type="OTHER",
        model_parameter_schema=(
            ("o", "func_auto_closing", "option_auto_closing"),
            ("o", "func_auto_closing_ped", "option_auto_closing"),
        ),
        parameters=(2, 1),
    )
    assert pedestrian_auto_close_delay_seconds(hub) == 30.0


def test_dedicated_ped_auto_close_off_does_not_fall_back_to_normal() -> None:
    hub = SimpleNamespace(
        controller_type="OTHER",
        configured_controller_type="OTHER",
        parameter_model_type="OTHER",
        model_parameter_schema=(
            ("o", "func_auto_closing", "option_auto_closing"),
            ("o", "func_auto_closing_ped", "option_auto_closing"),
        ),
        parameters=(2, 0),
    )
    assert pedestrian_auto_close_delay_seconds(hub) is None


def test_percentage_based_pedestrian_mode_is_not_treated_as_timer() -> None:
    hub = _hub("PS23065")
    _set_pedestrian_raw_value(hub, 1)
    assert pedestrian_open_duration_seconds(hub) is None


def test_shared_wrapper_arms_display_before_command_runs() -> None:
    hub = _hub("PS21053C")
    _set_legacy_timers(hub)

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
    _set_legacy_timers(hub)

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
    _set_legacy_timers(hub)

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


def test_reverse_live_position_before_ped_deadline_cannot_change_opening_state() -> None:
    hub = _hub("PS21053C")
    _set_legacy_timers(hub)

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

        cancel_pedestrian_display_cycle(hub, notify=False)

    asyncio.run(run_test())


def test_ped_deadline_transitions_to_open_and_arms_30_second_hold() -> None:
    hub = _hub("PS21053C")
    _set_legacy_timers(hub, pedestrian_raw=1, auto_close_raw=3)

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
        assert hub._tmt_pedestrian_display_deadline is not None
        assert hub._tmt_pedestrian_display_deadline > time.monotonic() + 28
        cancel_pedestrian_display_cycle(hub, notify=False)

    asyncio.run(run_test())


def test_closing_telemetry_is_ignored_during_configured_auto_close_hold() -> None:
    hub = _hub("PS21053C")
    _set_legacy_timers(hub, pedestrian_raw=1, auto_close_raw=3)

    async def run_test() -> None:
        assert begin_pedestrian_display_cycle(hub) is True
        hub.position = 40
        hub._last_live_position_monotonic = time.monotonic()

        hub._tmt_pedestrian_display_deadline = time.monotonic() - 1
        process_pedestrian_display_telemetry(hub)
        assert pedestrian_display_phase(hub) == "open"

        # Contradictory/stale closing frames before the 30-second hold expires
        # must not make HA say Closing early.
        hub.position = 20
        hub.movement = "closing"
        hub.is_operating = True
        hub._last_live_position_monotonic = time.monotonic() + 1
        hub._last_operating_status_monotonic = time.monotonic() + 1
        process_pedestrian_display_telemetry(hub)
        assert pedestrian_display_phase(hub) == "open"
        assert pedestrian_display_movement(hub) is None
        assert pedestrian_display_position(hub) == 40
        cancel_pedestrian_display_cycle(hub, notify=False)

    asyncio.run(run_test())


def test_auto_close_deadline_starts_closing_even_before_fresh_motion_frame() -> None:
    hub = _hub("PS21053C")
    _set_legacy_timers(hub, pedestrian_raw=1, auto_close_raw=3)

    async def run_test() -> None:
        assert begin_pedestrian_display_cycle(hub) is True
        hub.position = 40
        hub._last_live_position_monotonic = time.monotonic()

        hub._tmt_pedestrian_display_deadline = time.monotonic() - 1
        process_pedestrian_display_telemetry(hub)
        assert pedestrian_display_phase(hub) == "open"

        # Force the configured 30-second hold boundary to expire.
        hub._tmt_pedestrian_display_deadline = time.monotonic() - 1
        process_pedestrian_display_telemetry(hub)
        assert pedestrian_display_phase(hub) == "closing"
        assert pedestrian_display_movement(hub) == "closing"
        assert pedestrian_display_is_closed(hub) is False
        cancel_pedestrian_display_cycle(hub, notify=False)

    asyncio.run(run_test())


def test_fresh_live_zero_after_timed_closing_completes_cycle() -> None:
    hub = _hub("PS21053C")
    _set_legacy_timers(hub, pedestrian_raw=1, auto_close_raw=3)

    async def run_test() -> None:
        assert begin_pedestrian_display_cycle(hub) is True
        hub.position = 40
        hub._last_live_position_monotonic = time.monotonic()

        hub._tmt_pedestrian_display_deadline = time.monotonic() - 1
        process_pedestrian_display_telemetry(hub)
        hub._tmt_pedestrian_display_deadline = time.monotonic() - 1
        process_pedestrian_display_telemetry(hub)
        assert pedestrian_display_phase(hub) == "closing"

        hub.position = 0
        hub.is_operating = False
        hub.movement = None
        hub._last_live_position_monotonic = time.monotonic() + 2
        process_pedestrian_display_telemetry(hub)
        assert pedestrian_display_phase(hub) is None
        assert pedestrian_display_is_closed(hub) is True

    asyncio.run(run_test())


def test_auto_closing_off_keeps_post_open_phase_telemetry_driven() -> None:
    hub = _hub("PS21053C")
    _set_legacy_timers(hub, pedestrian_raw=1, auto_close_raw=0)

    async def run_test() -> None:
        assert begin_pedestrian_display_cycle(hub) is True
        hub.position = 40
        hub._last_live_position_monotonic = time.monotonic()
        process_pedestrian_display_telemetry(hub)

        hub._tmt_pedestrian_display_deadline = time.monotonic() - 1
        process_pedestrian_display_telemetry(hub)
        assert pedestrian_display_phase(hub) == "open"
        assert hub._tmt_pedestrian_display_deadline is None

        hub.position = 30
        hub.movement = "closing"
        hub.is_operating = True
        hub._last_live_position_monotonic = time.monotonic() + 1
        process_pedestrian_display_telemetry(hub)
        assert pedestrian_display_phase(hub) == "closing"
        cancel_pedestrian_display_cycle(hub, notify=False)

    asyncio.run(run_test())
