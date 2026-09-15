"""Stable Home Assistant presentation state for pedestrian gate cycles."""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any

from .model_parameter_schemas import parameter_options
from .parameters import PARAMETERS

_PEDESTRIAN_PARAMETER_KEYS = {"pedestrian_mode", "func_pedestrian_mode"}
_SECONDS_SUFFIX_RE = re.compile(
    r"(?<!\d)(\d+(?:\.\d+)?)\s*(?:seconds?|secs?|s)\b",
    re.IGNORECASE,
)
_SECONDS_PREFIX_RE = re.compile(r"\bseconds?[_\s-]*(\d+(?:\.\d+)?)\b", re.IGNORECASE)
_LEGACY_TIMED_MODELS = {"PS21053", "PS21053C"}
_PS25007_APP_MODEL = "PS25007"
_PS25007A_PARAMETER_MODEL = "PS25007A"

_PHASE_ATTR = "_tmt_pedestrian_display_phase"
_DEADLINE_ATTR = "_tmt_pedestrian_display_deadline"
_TASK_ATTR = "_tmt_pedestrian_display_task"
_LAST_LIVE_STAMP_ATTR = "_tmt_pedestrian_last_live_stamp"
_LAST_LIVE_POSITION_ATTR = "_tmt_pedestrian_last_live_position"
_PEAK_LIVE_POSITION_ATTR = "_tmt_pedestrian_peak_live_position"
_LIVE_SEEN_ATTR = "_tmt_pedestrian_live_position_seen"
_LAST_STATUS_STAMP_ATTR = "_tmt_pedestrian_last_status_stamp"


def _seconds_from_label(label: str) -> float | None:
    match = _SECONDS_SUFFIX_RE.search(label) or _SECONDS_PREFIX_RE.search(label)
    if match is None:
        return None
    seconds = float(match.group(1))
    return seconds if seconds > 0 else None


def _legacy_pedestrian_seconds(hub: Any, values: tuple[int, ...] | list[int]) -> float | None:
    """Read the same 17-slot pedestrian option used by the legacy HA selects."""
    controller_type = str(getattr(hub, "controller_type", "") or "").upper()
    configured_type = str(
        getattr(hub, "configured_controller_type", "") or ""
    ).upper()
    parameter_model = str(getattr(hub, "parameter_model_type", "") or "").upper()
    legacy_profile = controller_type in _LEGACY_TIMED_MODELS or (
        configured_type == _PS25007_APP_MODEL
        and parameter_model == _PS25007A_PARAMETER_MODEL
    )
    if not legacy_profile or len(values) != len(PARAMETERS):
        return None

    for index, definition in enumerate(PARAMETERS):
        if definition.key != "pedestrian_mode":
            continue
        try:
            raw_value = int(values[index])
        except (IndexError, TypeError, ValueError):
            return None
        if not 0 <= raw_value < len(definition.options):
            return None
        return _seconds_from_label(str(definition.options[raw_value]))
    return None


def pedestrian_open_duration_seconds(hub: Any) -> float | None:
    """Return the active time-based pedestrian setting from the vendor schema.

    PS21053/PS21053C and the verified PS25007 -> PS25007A alias expose their
    17-slot controls through ``parameters.PARAMETERS`` in Home Assistant, so
    read those profiles from that exact same option source first. Other models
    stay schema-driven. Percentage-based partial opening and simple OFF/ON
    pedestrian modes intentionally return None.
    """
    values = getattr(hub, "parameters", None)
    if values is None:
        return None

    legacy_seconds = _legacy_pedestrian_seconds(hub, values)
    if legacy_seconds is not None:
        return legacy_seconds

    schema = getattr(hub, "model_parameter_schema", None)
    if schema is None or len(schema) != len(values):
        return None

    for index, spec in enumerate(schema):
        try:
            key = str(spec[1])
        except (IndexError, TypeError):
            continue
        if key not in _PEDESTRIAN_PARAMETER_KEYS:
            continue

        options = parameter_options(spec)
        if not options:
            continue
        try:
            raw_value = int(values[index])
        except (IndexError, TypeError, ValueError):
            continue
        if not 0 <= raw_value < len(options):
            continue

        seconds = _seconds_from_label(str(options[raw_value]))
        if seconds is not None:
            return seconds

    return None


def pedestrian_display_phase(hub: Any) -> str | None:
    """Return the current presentation phase: opening, open, closing or None."""
    return getattr(hub, _PHASE_ATTR, None)


def pedestrian_display_movement(hub: Any) -> str | None:
    """Return movement for the HA cover, suppressing contradictory raw frames."""
    phase = pedestrian_display_phase(hub)
    if phase == "opening":
        return "opening"
    if phase == "closing":
        return "closing"
    if phase == "open":
        return None
    return getattr(hub, "movement", None)


def pedestrian_display_is_closed(hub: Any) -> bool | None:
    """Return the cover closed state with an active PED cycle taking priority."""
    phase = pedestrian_display_phase(hub)
    if phase in {"opening", "open", "closing"}:
        return False
    position = getattr(hub, "position", None)
    return None if position is None else position == 0


def pedestrian_display_position(hub: Any) -> int | None:
    """Return a stable cover position while a timed pedestrian cycle is active.

    During opening/open, stale controller frames may temporarily write raw 0%
    even though the gate is in the pedestrian cycle. Hide that contradictory 0%
    and retain the highest dedicated live position observed in this cycle. Once
    real closing is proven, expose the raw live position again.
    """
    phase = pedestrian_display_phase(hub)
    raw_position = getattr(hub, "position", None)
    if phase not in {"opening", "open"}:
        return raw_position

    peak = getattr(hub, _PEAK_LIVE_POSITION_ATTR, None)
    if isinstance(peak, int) and peak > 0:
        return peak
    if isinstance(raw_position, int) and raw_position > 0:
        return raw_position
    return None


def begin_pedestrian_display_cycle(hub: Any) -> bool:
    """Start the presentation cycle before the PED command is sent.

    For time-based pedestrian modes, the configured duration is authoritative
    for the opening presentation phase. No RS, Shadow, or /position frame may
    end or reverse that opening phase before its deadline.
    """
    duration = pedestrian_open_duration_seconds(hub)
    if duration is None:
        return False

    cancel_pedestrian_display_cycle(hub, notify=False)
    deadline = time.monotonic() + duration
    setattr(hub, _PHASE_ATTR, "opening")
    setattr(hub, _DEADLINE_ATTR, deadline)
    setattr(hub, _LAST_LIVE_STAMP_ATTR, getattr(hub, "_last_live_position_monotonic", None))
    current_position = getattr(hub, "position", None)
    setattr(hub, _LAST_LIVE_POSITION_ATTR, current_position)
    setattr(hub, _PEAK_LIVE_POSITION_ATTR, current_position)
    setattr(hub, _LIVE_SEEN_ATTR, False)
    setattr(hub, _LAST_STATUS_STAMP_ATTR, getattr(hub, "_last_operating_status_monotonic", None))

    task = asyncio.create_task(
        _finish_opening_phase(hub, deadline),
        name=f"tmt_chow_pedestrian_display_{getattr(hub, 'uuid', 'gate')}",
    )
    setattr(hub, _TASK_ATTR, task)
    hub._notify()
    return True


async def async_pedestrian_open_with_display(hub: Any) -> None:
    """Run PED OPEN with the same presentation state from every entry point.

    The integration has two user-facing entry points: the normal ButtonEntity
    and the custom cover more-info control, which calls the integration service.
    Both must arm the timed presentation state before the command can emit any
    controller telemetry. On command failure or cancellation, clear only the
    presentation overlay and re-raise the original error.
    """
    display_started = begin_pedestrian_display_cycle(hub)
    try:
        await hub.async_pedestrian_open()
    except asyncio.CancelledError:
        if display_started:
            cancel_pedestrian_display_cycle(hub)
        raise
    except Exception:
        if display_started:
            cancel_pedestrian_display_cycle(hub)
        raise


async def _finish_opening_phase(hub: Any, deadline: float) -> None:
    try:
        await asyncio.sleep(max(0.0, deadline - time.monotonic()))
    except asyncio.CancelledError:
        return

    if getattr(hub, _DEADLINE_ATTR, None) != deadline:
        return
    setattr(hub, _DEADLINE_ATTR, None)
    setattr(hub, _TASK_ATTR, None)
    if pedestrian_display_phase(hub) == "opening":
        setattr(hub, _PHASE_ATTR, "open")
        hub._notify()


def cancel_pedestrian_display_cycle(hub: Any, *, notify: bool = True) -> None:
    """Clear any active pedestrian presentation overlay."""
    task = getattr(hub, _TASK_ATTR, None)
    if task is not None and not task.done():
        task.cancel()
    setattr(hub, _TASK_ATTR, None)
    setattr(hub, _PHASE_ATTR, None)
    setattr(hub, _DEADLINE_ATTR, None)
    setattr(hub, _LAST_LIVE_STAMP_ATTR, None)
    setattr(hub, _LAST_LIVE_POSITION_ATTR, None)
    setattr(hub, _PEAK_LIVE_POSITION_ATTR, None)
    setattr(hub, _LIVE_SEEN_ATTR, False)
    setattr(hub, _LAST_STATUS_STAMP_ATTR, None)
    if notify:
        hub._notify()


def _record_opening_window_telemetry(hub: Any) -> None:
    """Track useful telemetry during opening without allowing a state transition."""
    live_stamp = getattr(hub, "_last_live_position_monotonic", None)
    previous_live_stamp = getattr(hub, _LAST_LIVE_STAMP_ATTR, None)
    if live_stamp is not None and live_stamp != previous_live_stamp:
        setattr(hub, _LIVE_SEEN_ATTR, True)
        position = getattr(hub, "position", None)
        last_position = getattr(hub, _LAST_LIVE_POSITION_ATTR, None)
        peak_position = getattr(hub, _PEAK_LIVE_POSITION_ATTR, None)

        if position is not None:
            peak_position = position if peak_position is None else max(peak_position, position)
            setattr(hub, _PEAK_LIVE_POSITION_ATTR, peak_position)
            # While the configured opening duration is active, do not move the
            # baseline backwards. A transient 40 -> 0 -> 40 sequence must not be
            # interpreted as automatic closing before the timer expires.
            if last_position is None or position > last_position:
                setattr(hub, _LAST_LIVE_POSITION_ATTR, position)

        setattr(hub, _LAST_LIVE_STAMP_ATTR, live_stamp)

    status_stamp = getattr(hub, "_last_operating_status_monotonic", None)
    previous_status_stamp = getattr(hub, _LAST_STATUS_STAMP_ATTR, None)
    if status_stamp is not None and status_stamp != previous_status_stamp:
        setattr(hub, _LAST_STATUS_STAMP_ATTR, status_stamp)


def process_pedestrian_display_telemetry(hub: Any) -> None:
    """Advance an active presentation cycle using only post-window evidence.

    During the configured time-based opening window the presentation is locked
    to `opening`; all contradictory RS, Shadow and /position direction changes
    are ignored for presentation purposes. After the deadline, fresh closing
    telemetry may advance the state to `closing`. A final dedicated live 0%
    ends the cycle. This is intentionally stricter than the raw controller state
    because the real devices can emit out-of-order/stale frames during PED.
    """
    phase = pedestrian_display_phase(hub)
    if phase is None:
        return

    deadline = getattr(hub, _DEADLINE_ATTR, None)
    if phase == "opening":
        if deadline is not None and time.monotonic() < deadline:
            _record_opening_window_telemetry(hub)
            return
        setattr(hub, _PHASE_ATTR, "open")
        setattr(hub, _DEADLINE_ATTR, None)
        phase = "open"

    live_stamp = getattr(hub, "_last_live_position_monotonic", None)
    previous_live_stamp = getattr(hub, _LAST_LIVE_STAMP_ATTR, None)
    if live_stamp is not None and live_stamp != previous_live_stamp:
        setattr(hub, _LIVE_SEEN_ATTR, True)
        position = getattr(hub, "position", None)
        last_position = getattr(hub, _LAST_LIVE_POSITION_ATTR, None)
        peak_position = getattr(hub, _PEAK_LIVE_POSITION_ATTR, None)

        if position is not None:
            peak_position = position if peak_position is None else max(peak_position, position)
            setattr(hub, _PEAK_LIVE_POSITION_ATTR, peak_position)

            if (
                last_position is not None
                and peak_position is not None
                and peak_position > 5
                and position < last_position
            ):
                setattr(hub, _PHASE_ATTR, "closing")
                phase = "closing"

            setattr(hub, _LAST_LIVE_POSITION_ATTR, position)

            if phase == "closing" and position == 0:
                cancel_pedestrian_display_cycle(hub, notify=False)
                return

        setattr(hub, _LAST_LIVE_STAMP_ATTR, live_stamp)

    status_stamp = getattr(hub, "_last_operating_status_monotonic", None)
    previous_status_stamp = getattr(hub, _LAST_STATUS_STAMP_ATTR, None)
    if status_stamp is not None and status_stamp != previous_status_stamp:
        setattr(hub, _LAST_STATUS_STAMP_ATTR, status_stamp)
        phase = pedestrian_display_phase(hub)
        if phase == "open" and getattr(hub, "is_operating", None) is True:
            if getattr(hub, "movement", None) == "closing":
                setattr(hub, _PHASE_ATTR, "closing")
                phase = "closing"

    # Fallback for controllers that never publish the dedicated position topic.
    # If live position has been seen, do NOT trust a stopped Shadow 0% here.
    phase = pedestrian_display_phase(hub)
    if (
        phase == "closing"
        and not getattr(hub, _LIVE_SEEN_ATTR, False)
        and getattr(hub, "position", None) == 0
        and getattr(hub, "is_operating", None) is False
    ):
        cancel_pedestrian_display_cycle(hub, notify=False)
