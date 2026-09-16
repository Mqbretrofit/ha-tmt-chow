"""Regression tests for beta.17 pedestrian presentation-state hardening."""

from __future__ import annotations

import time
from types import SimpleNamespace

from custom_components.tmt_chow import pedestrian_state as ps
from custom_components.tmt_chow.pedestrian_state_v17 import (
    process_pedestrian_display_telemetry,
)


class _Hub(SimpleNamespace):
    def _notify(self) -> None:
        return None


def _open_hub(*, live_seen: bool = True) -> _Hub:
    return _Hub(
        position=60,
        is_operating=False,
        movement=None,
        _last_live_position_monotonic=10.0,
        _last_operating_status_monotonic=10.0,
        _tmt_pedestrian_display_phase="open",
        _tmt_pedestrian_display_deadline=None,
        _tmt_pedestrian_display_task=None,
        _tmt_pedestrian_auto_close_delay=None,
        _tmt_pedestrian_last_live_stamp=10.0,
        _tmt_pedestrian_last_live_position=60,
        _tmt_pedestrian_peak_live_position=60,
        _tmt_pedestrian_live_position_seen=live_seen,
        _tmt_pedestrian_last_status_stamp=10.0,
        _tmt_pedestrian_closing_position_count=0,
        _tmt_pedestrian_closing_status_count=0,
    )


def test_live_position_cycle_ignores_repeated_false_closing_status() -> None:
    hub = _open_hub(live_seen=True)

    hub.is_operating = True
    hub.movement = "closing"
    hub._last_operating_status_monotonic = 11.0
    process_pedestrian_display_telemetry(hub)
    assert ps.pedestrian_display_phase(hub) == "open"

    hub._last_operating_status_monotonic = 12.0
    process_pedestrian_display_telemetry(hub)
    assert ps.pedestrian_display_phase(hub) == "open"
    assert hub._tmt_pedestrian_closing_status_count == 2


def test_external_close_can_finish_from_fresh_stopped_zero_status() -> None:
    hub = _open_hub(live_seen=True)

    # Two fresh closing statuses are tracked as corroborating evidence but do
    # not change the displayed Open state because dedicated /position exists.
    hub.is_operating = True
    hub.movement = "closing"
    hub._last_operating_status_monotonic = 11.0
    process_pedestrian_display_telemetry(hub)
    hub._last_operating_status_monotonic = 12.0
    process_pedestrian_display_telemetry(hub)
    assert ps.pedestrian_display_phase(hub) == "open"

    # The gate is then closed externally from the vendor app/remote. A fresh
    # stopped 0% status may complete the overlay even if no new /position came.
    hub.position = 0
    hub.is_operating = False
    hub.movement = None
    hub._last_operating_status_monotonic = 13.0
    process_pedestrian_display_telemetry(hub)

    assert ps.pedestrian_display_phase(hub) is None
    assert ps.pedestrian_display_is_closed(hub) is True


def test_two_decreasing_live_positions_still_prove_real_closing() -> None:
    hub = _open_hub(live_seen=True)

    hub.position = 50
    hub._last_live_position_monotonic = 11.0
    process_pedestrian_display_telemetry(hub)
    assert ps.pedestrian_display_phase(hub) == "open"

    hub.position = 40
    hub._last_live_position_monotonic = 12.0
    process_pedestrian_display_telemetry(hub)
    assert ps.pedestrian_display_phase(hub) == "closing"
    assert hub._tmt_pedestrian_v17_closing_live_seen is True


def test_fresh_live_zero_finishes_confirmed_closing() -> None:
    hub = _open_hub(live_seen=True)

    hub.position = 50
    hub._last_live_position_monotonic = 11.0
    process_pedestrian_display_telemetry(hub)
    hub.position = 40
    hub._last_live_position_monotonic = 12.0
    process_pedestrian_display_telemetry(hub)
    assert ps.pedestrian_display_phase(hub) == "closing"

    hub.position = 0
    hub.is_operating = False
    hub.movement = None
    hub._last_live_position_monotonic = 13.0
    process_pedestrian_display_telemetry(hub)
    assert ps.pedestrian_display_phase(hub) is None
    assert ps.pedestrian_display_is_closed(hub) is True


def test_status_only_controller_keeps_repeated_status_fallback() -> None:
    hub = _open_hub(live_seen=False)
    hub._last_live_position_monotonic = None
    hub._tmt_pedestrian_last_live_stamp = None

    hub.is_operating = True
    hub.movement = "closing"
    hub._last_operating_status_monotonic = 11.0
    process_pedestrian_display_telemetry(hub)
    assert ps.pedestrian_display_phase(hub) == "open"

    hub._last_operating_status_monotonic = 12.0
    process_pedestrian_display_telemetry(hub)
    assert ps.pedestrian_display_phase(hub) == "closing"


def test_timed_auto_close_boundary_is_unchanged() -> None:
    hub = _open_hub(live_seen=True)
    hub._tmt_pedestrian_display_deadline = time.monotonic() - 1

    process_pedestrian_display_telemetry(hub)

    assert ps.pedestrian_display_phase(hub) == "closing"
