"""Stable Home Assistant presentation state for pedestrian gate cycles."""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any

from .model_parameter_schemas import parameter_options

_PEDESTRIAN_PARAMETER_KEYS = {"pedestrian_mode", "func_pedestrian_mode"}
_SECONDS_SUFFIX_RE = re.compile(
    r"(?<!\d)(\d+(?:\.\d+)?)\s*(?:seconds?|secs?|s)\b",
    re.IGNORECASE,
)
_SECONDS_PREFIX_RE = re.compile(r"\bseconds?[_\s-]*(\d+(?:\.\d+)?)\b", re.IGNORECASE)

_PHASE_ATTR = "_tmt_pedestrian_display_phase"
_DEADLINE_ATTR = "_tmt_pedestrian_display_deadline"
_TASK_ATTR = "_tmt_pedestrian_display_task"
_LAST_LIVE_STAMP_ATTR = "_tmt_pedestrian_last_live_stamp"
_LAST_LIVE_POSITION_ATTR = "_tmt_pedestrian_last_live_position"
_PEAK_LIVE_POSITION_ATTR = "_tmt_pedestrian_peak_live_position"
_LIVE_SEEN_ATTR = "_tmt_pedestrian_live_position_seen"
_LAST_STATUS_STAMP_ATTR = "_tmt_pedestrian_last_status_stamp"


def pedestrian_open_duration_seconds(hub: Any) -> float | None:
    """Return the active time-based pedestrian setting from the vendor schema.

    Only options explicitly expressed as seconds are accepted. Percentage-based
    partial opening and simple OFF/ON pedestrian modes intentionally return None.
    """
    schema = getattr(hub, "model_parameter_schema", None)
    values = getattr(hub, "parameters", None)
    if schema is None or values is None or len(schema) != len(values):
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

        label = str(options[raw_value])
        match = _SECONDS_SUFFIX_RE.search(label) or _SECONDS_PREFIX_RE.search(label)
        if match is None:
            continue
        seconds = float(match.group(1))
        return seconds if seconds > 0 else None

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


def begin_pedestrian_display_cycle(hub: Any) -> bool:
    """Start the presentation cycle before the PED command is sent.

    Starting before the publish/ACK wait is essential: some controllers send
    transient/stale RS or Shadow frames while the PED command is still waiting
    for its acknowledgement. Those frames must never make HA flicker through
    closing/closed while the configured pedestrian opening phase is running.
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


def process_pedestrian_display_telemetry(hub: Any) -> None:
    """Advance an active presentation cycle using only strong live evidence.

    During the configured opening window the overlay wins over contradictory
    RS/Shadow frames. After that window, a fresh closing operating-status or a
    decreasing dedicated /position value moves the display to closing. Once a
    controller has emitted dedicated position telemetry in this cycle, only a
    fresh live 0% may end the overlay; this prevents stale stopped Shadow frames
    from making the cover jump to closed too early.
    """
    phase = pedestrian_display_phase(hub)
    if phase is None:
        return

    deadline = getattr(hub, _DEADLINE_ATTR, None)
    if phase == "opening" and deadline is not None and time.monotonic() >= deadline:
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
