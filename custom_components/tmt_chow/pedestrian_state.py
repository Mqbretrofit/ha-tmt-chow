"""Stable Home Assistant presentation state for pedestrian gate cycles."""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any

from .model_parameter_schemas import parameter_options
from .parameters import PARAMETERS

_PEDESTRIAN_PARAMETER_KEYS = {"pedestrian_mode", "func_pedestrian_mode"}
_AUTO_CLOSE_PARAMETER_KEYS = ("func_auto_closing_ped", "func_auto_closing")
_SECONDS_SUFFIX_RE = re.compile(
    r"(?<!\d)(\d+(?:\.\d+)?)\s*(?:seconds?|secs?|s)\b",
    re.IGNORECASE,
)
_SECONDS_PREFIX_RE = re.compile(r"\bseconds?[_\s-]*(\d+(?:\.\d+)?)\b", re.IGNORECASE)
_LEGACY_TIMED_MODELS = {"PS21053", "PS21053C"}
_PS25007_APP_MODEL = "PS25007"
_PS25007A_PARAMETER_MODEL = "PS25007A"
_CLOSING_CONFIRMATION_COUNT = 2

_PHASE_ATTR = "_tmt_pedestrian_display_phase"
_DEADLINE_ATTR = "_tmt_pedestrian_display_deadline"
_TASK_ATTR = "_tmt_pedestrian_display_task"
_AUTO_CLOSE_DELAY_ATTR = "_tmt_pedestrian_auto_close_delay"
_LAST_LIVE_STAMP_ATTR = "_tmt_pedestrian_last_live_stamp"
_LAST_LIVE_POSITION_ATTR = "_tmt_pedestrian_last_live_position"
_PEAK_LIVE_POSITION_ATTR = "_tmt_pedestrian_peak_live_position"
_LIVE_SEEN_ATTR = "_tmt_pedestrian_live_position_seen"
_LAST_STATUS_STAMP_ATTR = "_tmt_pedestrian_last_status_stamp"
_CLOSING_POSITION_COUNT_ATTR = "_tmt_pedestrian_closing_position_count"
_CLOSING_STATUS_COUNT_ATTR = "_tmt_pedestrian_closing_status_count"


def _seconds_from_label(label: str) -> float | None:
    match = _SECONDS_SUFFIX_RE.search(label) or _SECONDS_PREFIX_RE.search(label)
    if match is None:
        return None
    seconds = float(match.group(1))
    return seconds if seconds > 0 else None


def _is_legacy_17_slot_profile(hub: Any, values: tuple[int, ...] | list[int]) -> bool:
    controller_type = str(getattr(hub, "controller_type", "") or "").upper()
    configured_type = str(
        getattr(hub, "configured_controller_type", "") or ""
    ).upper()
    parameter_model = str(getattr(hub, "parameter_model_type", "") or "").upper()
    return len(values) == len(PARAMETERS) and (
        controller_type in _LEGACY_TIMED_MODELS
        or (
            configured_type == _PS25007_APP_MODEL
            and parameter_model == _PS25007A_PARAMETER_MODEL
        )
    )


def _legacy_option_seconds(
    hub: Any,
    values: tuple[int, ...] | list[int],
    key: str,
) -> tuple[bool, float | None]:
    """Read one option from the exact 17-slot definitions used by HA selects."""
    if not _is_legacy_17_slot_profile(hub, values):
        return False, None

    for index, definition in enumerate(PARAMETERS):
        if definition.key != key:
            continue
        try:
            raw_value = int(values[index])
        except (IndexError, TypeError, ValueError):
            return True, None
        if not 0 <= raw_value < len(definition.options):
            return True, None
        return True, _seconds_from_label(str(definition.options[raw_value]))
    return False, None


def _schema_option_seconds(
    hub: Any,
    values: tuple[int, ...] | list[int],
    key: str,
) -> tuple[bool, float | None]:
    """Return whether a schema key exists and its selected time in seconds."""
    schema = getattr(hub, "model_parameter_schema", None)
    if schema is None or len(schema) != len(values):
        return False, None

    for index, spec in enumerate(schema):
        try:
            spec_key = str(spec[1])
        except (IndexError, TypeError):
            continue
        if spec_key != key:
            continue

        options = parameter_options(spec)
        if not options:
            return True, None
        try:
            raw_value = int(values[index])
        except (IndexError, TypeError, ValueError):
            return True, None
        if not 0 <= raw_value < len(options):
            return True, None
        return True, _seconds_from_label(str(options[raw_value]))

    return False, None


def pedestrian_open_duration_seconds(hub: Any) -> float | None:
    """Return the active time-based pedestrian opening setting.

    PS21053/PS21053C and the verified PS25007 -> PS25007A alias expose their
    17-slot controls through ``parameters.PARAMETERS`` in Home Assistant, so
    read those profiles from that exact same option source first. Other models
    stay schema-driven. Percentage-based partial opening and simple OFF/ON
    pedestrian modes intentionally return None.
    """
    values = getattr(hub, "parameters", None)
    if values is None:
        return None

    found, seconds = _legacy_option_seconds(hub, values, "pedestrian_mode")
    if found:
        return seconds

    for key in _PEDESTRIAN_PARAMETER_KEYS:
        found, seconds = _schema_option_seconds(hub, values, key)
        if found:
            return seconds

    return None


def pedestrian_auto_close_delay_seconds(hub: Any) -> float | None:
    """Return the hold-open delay used before a PED cycle starts closing.

    A dedicated ``Auto-closing(Pedestrian Mode)`` parameter is authoritative
    when a controller exposes one. If it does not, fall back to the controller's
    normal Auto-closing parameter. An explicit OFF/non-time value means there is
    no synthetic closing deadline and the presentation remains telemetry-driven.
    """
    values = getattr(hub, "parameters", None)
    if values is None:
        return None

    # The verified 17-slot PS21053/PS21053C/PS25007A profile has no separate
    # pedestrian auto-close field, so use the same Automatic Closing option the
    # Home Assistant select exposes.
    found, seconds = _legacy_option_seconds(hub, values, "automatic_closing")
    if found:
        return seconds

    # A dedicated pedestrian timer, including an explicit OFF value, overrides
    # the normal auto-closing setting. Only fall back when that field is absent.
    found, seconds = _schema_option_seconds(hub, values, "func_auto_closing_ped")
    if found:
        return seconds

    found, seconds = _schema_option_seconds(hub, values, "func_auto_closing")
    if found:
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
    closing is confirmed or the configured auto-close delay expires, expose the
    raw closing position again.
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


def _reset_closing_confirmation(hub: Any) -> None:
    setattr(hub, _CLOSING_POSITION_COUNT_ATTR, 0)
    setattr(hub, _CLOSING_STATUS_COUNT_ATTR, 0)


def begin_pedestrian_display_cycle(hub: Any) -> bool:
    """Start the timed PED presentation before the command is sent.

    For a second-based pedestrian mode, the configured pedestrian time defines
    the complete ``opening`` phase. If Auto-closing is also a time value, that
    setting then defines the complete ``open`` hold phase. Contradictory raw
    telemetry cannot advance either timed phase early.
    """
    opening_duration = pedestrian_open_duration_seconds(hub)
    if opening_duration is None:
        return False

    auto_close_delay = pedestrian_auto_close_delay_seconds(hub)
    cancel_pedestrian_display_cycle(hub, notify=False)
    opening_deadline = time.monotonic() + opening_duration
    setattr(hub, _PHASE_ATTR, "opening")
    setattr(hub, _DEADLINE_ATTR, opening_deadline)
    setattr(hub, _AUTO_CLOSE_DELAY_ATTR, auto_close_delay)
    setattr(
        hub,
        _LAST_LIVE_STAMP_ATTR,
        getattr(hub, "_last_live_position_monotonic", None),
    )
    current_position = getattr(hub, "position", None)
    setattr(hub, _LAST_LIVE_POSITION_ATTR, current_position)
    setattr(hub, _PEAK_LIVE_POSITION_ATTR, current_position)
    setattr(hub, _LIVE_SEEN_ATTR, False)
    setattr(
        hub,
        _LAST_STATUS_STAMP_ATTR,
        getattr(hub, "_last_operating_status_monotonic", None),
    )
    _reset_closing_confirmation(hub)

    task = asyncio.create_task(
        _run_timed_phases(hub, opening_deadline, auto_close_delay),
        name=f"tmt_chow_pedestrian_display_{getattr(hub, 'uuid', 'gate')}",
    )
    setattr(hub, _TASK_ATTR, task)
    hub._notify()
    return True


async def async_pedestrian_open_with_display(hub: Any) -> None:
    """Run PED OPEN with the same presentation state from every entry point."""
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


def _transition_to_open(hub: Any, opening_deadline: float) -> float | None:
    """Finish opening and return the optional auto-close deadline."""
    if pedestrian_display_phase(hub) != "opening":
        return None

    setattr(hub, _PHASE_ATTR, "open")
    _reset_closing_confirmation(hub)
    auto_close_delay = getattr(hub, _AUTO_CLOSE_DELAY_ATTR, None)
    if auto_close_delay is None:
        setattr(hub, _DEADLINE_ATTR, None)
        hub._notify()
        return None

    close_deadline = opening_deadline + float(auto_close_delay)
    setattr(hub, _DEADLINE_ATTR, close_deadline)
    hub._notify()
    return close_deadline


def _transition_to_closing(hub: Any) -> None:
    """Start the displayed closing phase after timer or telemetry confirmation."""
    if pedestrian_display_phase(hub) != "open":
        return
    setattr(hub, _PHASE_ATTR, "closing")
    setattr(hub, _DEADLINE_ATTR, None)
    _reset_closing_confirmation(hub)
    # Require post-transition evidence before accepting an endpoint from a stale
    # raw value already present when the phase changed.
    setattr(
        hub,
        _LAST_LIVE_STAMP_ATTR,
        getattr(hub, "_last_live_position_monotonic", None),
    )
    setattr(
        hub,
        _LAST_STATUS_STAMP_ATTR,
        getattr(hub, "_last_operating_status_monotonic", None),
    )
    hub._notify()


async def _run_timed_phases(
    hub: Any,
    opening_deadline: float,
    auto_close_delay: float | None,
) -> None:
    try:
        await asyncio.sleep(max(0.0, opening_deadline - time.monotonic()))
    except asyncio.CancelledError:
        return

    if (
        getattr(hub, _DEADLINE_ATTR, None) != opening_deadline
        or pedestrian_display_phase(hub) != "opening"
    ):
        return

    close_deadline = _transition_to_open(hub, opening_deadline)
    if auto_close_delay is None or close_deadline is None:
        setattr(hub, _TASK_ATTR, None)
        return

    try:
        await asyncio.sleep(max(0.0, close_deadline - time.monotonic()))
    except asyncio.CancelledError:
        return

    if (
        getattr(hub, _DEADLINE_ATTR, None) != close_deadline
        or pedestrian_display_phase(hub) != "open"
    ):
        return

    _transition_to_closing(hub)
    setattr(hub, _TASK_ATTR, None)


def cancel_pedestrian_display_cycle(hub: Any, *, notify: bool = True) -> None:
    """Clear any active pedestrian presentation overlay."""
    task = getattr(hub, _TASK_ATTR, None)
    if task is not None and not task.done():
        task.cancel()
    setattr(hub, _TASK_ATTR, None)
    setattr(hub, _PHASE_ATTR, None)
    setattr(hub, _DEADLINE_ATTR, None)
    setattr(hub, _AUTO_CLOSE_DELAY_ATTR, None)
    setattr(hub, _LAST_LIVE_STAMP_ATTR, None)
    setattr(hub, _LAST_LIVE_POSITION_ATTR, None)
    setattr(hub, _PEAK_LIVE_POSITION_ATTR, None)
    setattr(hub, _LIVE_SEEN_ATTR, False)
    setattr(hub, _LAST_STATUS_STAMP_ATTR, None)
    _reset_closing_confirmation(hub)
    if notify:
        hub._notify()


def _record_timed_phase_telemetry(hub: Any) -> None:
    """Track useful telemetry without allowing a timed state transition."""
    live_stamp = getattr(hub, "_last_live_position_monotonic", None)
    previous_live_stamp = getattr(hub, _LAST_LIVE_STAMP_ATTR, None)
    if live_stamp is not None and live_stamp != previous_live_stamp:
        setattr(hub, _LIVE_SEEN_ATTR, True)
        position = getattr(hub, "position", None)
        last_position = getattr(hub, _LAST_LIVE_POSITION_ATTR, None)
        peak_position = getattr(hub, _PEAK_LIVE_POSITION_ATTR, None)

        if position is not None:
            peak_position = (
                position if peak_position is None else max(peak_position, position)
            )
            setattr(hub, _PEAK_LIVE_POSITION_ATTR, peak_position)
            if last_position is None or position > last_position:
                setattr(hub, _LAST_LIVE_POSITION_ATTR, position)

        setattr(hub, _LAST_LIVE_STAMP_ATTR, live_stamp)

    status_stamp = getattr(hub, "_last_operating_status_monotonic", None)
    previous_status_stamp = getattr(hub, _LAST_STATUS_STAMP_ATTR, None)
    if status_stamp is not None and status_stamp != previous_status_stamp:
        setattr(hub, _LAST_STATUS_STAMP_ATTR, status_stamp)


def _record_untimed_open_live_position(hub: Any, position: int) -> bool:
    """Return True only after repeated live decreases prove real closing.

    A single 40 -> 0 update is not enough: PS25007A real-hardware testing with
    Auto-closing OFF showed that an isolated stale 0% can arrive while the gate
    remains physically parked at its pedestrian position. Two consecutive
    decreasing dedicated /position updates are required before the presentation
    leaves ``open``.
    """
    last_position = getattr(hub, _LAST_LIVE_POSITION_ATTR, None)
    peak_position = getattr(hub, _PEAK_LIVE_POSITION_ATTR, None)
    count = int(getattr(hub, _CLOSING_POSITION_COUNT_ATTR, 0) or 0)

    if (
        last_position is not None
        and peak_position is not None
        and peak_position > 5
        and position < last_position
    ):
        count += 1
    elif last_position is not None and position > last_position:
        count = 0

    setattr(hub, _CLOSING_POSITION_COUNT_ATTR, count)
    setattr(hub, _LAST_LIVE_POSITION_ATTR, position)
    return count >= _CLOSING_CONFIRMATION_COUNT


def _record_untimed_open_status(hub: Any) -> bool:
    """Return True only after repeated operating/closing status confirmation."""
    count = int(getattr(hub, _CLOSING_STATUS_COUNT_ATTR, 0) or 0)
    if (
        getattr(hub, "is_operating", None) is True
        and getattr(hub, "movement", None) == "closing"
    ):
        count += 1
    else:
        count = 0
    setattr(hub, _CLOSING_STATUS_COUNT_ATTR, count)
    return count >= _CLOSING_CONFIRMATION_COUNT


def process_pedestrian_display_telemetry(hub: Any) -> None:
    """Advance the PED presentation while respecting configured timers.

    ``opening`` is locked until Pedestrian Mode seconds expire. When a timed
    Auto-closing value exists, ``open`` is then locked for exactly that delay and
    ``closing`` starts at the timer boundary. With Auto-closing OFF/unknown, an
    isolated stale 0% or one contradictory closing status cannot collapse the
    partial-open state: repeated live movement evidence is required.
    """
    phase = pedestrian_display_phase(hub)
    if phase is None:
        return

    now = time.monotonic()
    deadline = getattr(hub, _DEADLINE_ATTR, None)

    if phase == "opening":
        if deadline is not None and now < deadline:
            _record_timed_phase_telemetry(hub)
            return
        opening_deadline = float(deadline if deadline is not None else now)
        deadline = _transition_to_open(hub, opening_deadline)
        phase = "open"

    if phase == "open" and deadline is not None:
        if now < deadline:
            _record_timed_phase_telemetry(hub)
            return
        _transition_to_closing(hub)
        phase = "closing"

    live_stamp = getattr(hub, "_last_live_position_monotonic", None)
    previous_live_stamp = getattr(hub, _LAST_LIVE_STAMP_ATTR, None)
    if live_stamp is not None and live_stamp != previous_live_stamp:
        setattr(hub, _LIVE_SEEN_ATTR, True)
        position = getattr(hub, "position", None)
        peak_position = getattr(hub, _PEAK_LIVE_POSITION_ATTR, None)

        if position is not None:
            peak_position = (
                position if peak_position is None else max(peak_position, position)
            )
            setattr(hub, _PEAK_LIVE_POSITION_ATTR, peak_position)

            if (
                phase == "open"
                and getattr(hub, _DEADLINE_ATTR, None) is None
                and _record_untimed_open_live_position(hub, position)
            ):
                _transition_to_closing(hub)
                phase = "closing"

            if phase == "closing" and position == 0:
                # In the untimed path, reaching this branch on the same event
                # that confirmed closing means at least two consecutive live
                # decreases have already been observed. In the timed path,
                # _transition_to_closing() snapshots the current stamp, so only
                # a genuinely fresh post-boundary 0% reaches this branch.
                cancel_pedestrian_display_cycle(hub, notify=False)
                return

        setattr(hub, _LAST_LIVE_STAMP_ATTR, live_stamp)

    status_stamp = getattr(hub, "_last_operating_status_monotonic", None)
    previous_status_stamp = getattr(hub, _LAST_STATUS_STAMP_ATTR, None)
    if status_stamp is not None and status_stamp != previous_status_stamp:
        setattr(hub, _LAST_STATUS_STAMP_ATTR, status_stamp)
        phase = pedestrian_display_phase(hub)
        if (
            phase == "open"
            and getattr(hub, _DEADLINE_ATTR, None) is None
            and _record_untimed_open_status(hub)
        ):
            _transition_to_closing(hub)
            phase = "closing"

    # Fallback for controllers that never publish the dedicated position topic.
    phase = pedestrian_display_phase(hub)
    if (
        phase == "closing"
        and not getattr(hub, _LIVE_SEEN_ATTR, False)
        and getattr(hub, "position", None) == 0
        and getattr(hub, "is_operating", None) is False
    ):
        cancel_pedestrian_display_cycle(hub, notify=False)
