"""Beta.17 pedestrian presentation-state hardening.

This module intentionally wraps the beta.16 pedestrian state machine rather than
changing the command path.  Its job is only to decide when Home Assistant may
present a timed pedestrian cycle as closing/closed.

For Auto-closing OFF/unknown, once a dedicated /position update has been seen in
that PED cycle, controller status direction bits are no longer allowed to switch
the displayed state from open to closing.  Real decreasing /position telemetry
remains authoritative.  Repeated closing status is still tracked as corroborating
evidence so a later fresh stopped/0% status from an external vendor-app/remote
close can terminate the overlay even if no new /position update arrives.
"""

from __future__ import annotations

import time
from typing import Any

from . import pedestrian_state as ps

_LAST_PHASE_ATTR = "_tmt_pedestrian_v17_last_phase"
_CLOSING_LIVE_SEEN_ATTR = "_tmt_pedestrian_v17_closing_live_seen"
_CLOSING_LAST_LIVE_STAMP_ATTR = "_tmt_pedestrian_v17_closing_last_live_stamp"


def _sync_phase_tracking(hub: Any, phase: str | None) -> None:
    """Reset per-closing evidence whenever a new closing phase begins."""
    previous = getattr(hub, _LAST_PHASE_ATTR, None)
    if phase == "closing" and previous != "closing":
        setattr(hub, _CLOSING_LIVE_SEEN_ATTR, False)
        setattr(hub, _CLOSING_LAST_LIVE_STAMP_ATTR, None)
    elif phase in {None, "opening", "open"} and previous != phase:
        setattr(hub, _CLOSING_LIVE_SEEN_ATTR, False)
        setattr(hub, _CLOSING_LAST_LIVE_STAMP_ATTR, None)
    setattr(hub, _LAST_PHASE_ATTR, phase)


def _fresh_status_can_finish_closing(hub: Any, status_stamp: float | None) -> bool:
    """Accept an external close endpoint when it is not older than live position.

    A fresh stopped/0% status is enough when no dedicated position arrived after
    the displayed closing phase began.  If live position did arrive, only a
    status at least as new as that live sample may finish the overlay.
    """
    if getattr(hub, "position", None) != 0 or getattr(hub, "is_operating", None) is not False:
        return False

    if not getattr(hub, _CLOSING_LIVE_SEEN_ATTR, False):
        return True

    last_live_stamp = getattr(hub, _CLOSING_LAST_LIVE_STAMP_ATTR, None)
    if status_stamp is None or last_live_stamp is None:
        return False
    return float(status_stamp) >= float(last_live_stamp)


def process_pedestrian_display_telemetry(hub: Any) -> None:
    """Advance PED display state with stricter Auto-closing-OFF semantics.

    Timed opening and timed Auto-closing behavior stay identical to beta.16.
    The only changed path is untimed/open:

    * if this PED cycle already received dedicated /position telemetry, status
      direction bits alone cannot change Open -> Closing;
    * two consecutive decreasing /position updates still prove real closing;
    * status-only controllers may still use repeated closing status as fallback;
    * repeated closing status followed by a fresh stopped/0% status may complete
      an externally-triggered close without first displaying a false closing
      phase;
    * once displayed closing is genuine, either a fresh live 0% or a newer fresh
      stopped/0% status completes the cycle.
    """
    phase = ps.pedestrian_display_phase(hub)
    if phase is None:
        _sync_phase_tracking(hub, None)
        return

    _sync_phase_tracking(hub, phase)
    now = time.monotonic()
    deadline = getattr(hub, ps._DEADLINE_ATTR, None)

    if phase == "opening":
        if deadline is not None and now < deadline:
            ps._record_timed_phase_telemetry(hub)
            return
        opening_deadline = float(deadline if deadline is not None else now)
        deadline = ps._transition_to_open(hub, opening_deadline)
        phase = "open"
        _sync_phase_tracking(hub, phase)

    if phase == "open" and deadline is not None:
        if now < deadline:
            ps._record_timed_phase_telemetry(hub)
            return
        ps._transition_to_closing(hub)
        phase = "closing"
        _sync_phase_tracking(hub, phase)

    live_stamp = getattr(hub, "_last_live_position_monotonic", None)
    previous_live_stamp = getattr(hub, ps._LAST_LIVE_STAMP_ATTR, None)
    if live_stamp is not None and live_stamp != previous_live_stamp:
        setattr(hub, ps._LIVE_SEEN_ATTR, True)
        position = getattr(hub, "position", None)
        peak_position = getattr(hub, ps._PEAK_LIVE_POSITION_ATTR, None)

        if position is not None:
            peak_position = position if peak_position is None else max(peak_position, position)
            setattr(hub, ps._PEAK_LIVE_POSITION_ATTR, peak_position)

            if (
                phase == "open"
                and getattr(hub, ps._DEADLINE_ATTR, None) is None
                and ps._record_untimed_open_live_position(hub, position)
            ):
                ps._transition_to_closing(hub)
                phase = "closing"
                _sync_phase_tracking(hub, phase)
                # The same dedicated live update that confirmed reverse travel is
                # valid closing-phase evidence.
                setattr(hub, _CLOSING_LIVE_SEEN_ATTR, True)
                setattr(hub, _CLOSING_LAST_LIVE_STAMP_ATTR, live_stamp)

            elif phase == "closing":
                setattr(hub, _CLOSING_LIVE_SEEN_ATTR, True)
                setattr(hub, _CLOSING_LAST_LIVE_STAMP_ATTR, live_stamp)

            if phase == "closing" and position == 0:
                ps.cancel_pedestrian_display_cycle(hub, notify=False)
                _sync_phase_tracking(hub, None)
                return

        setattr(hub, ps._LAST_LIVE_STAMP_ATTR, live_stamp)

    status_stamp = getattr(hub, "_last_operating_status_monotonic", None)
    previous_status_stamp = getattr(hub, ps._LAST_STATUS_STAMP_ATTR, None)
    if status_stamp is not None and status_stamp != previous_status_stamp:
        prior_status_count = int(
            getattr(hub, ps._CLOSING_STATUS_COUNT_ATTR, 0) or 0
        )
        setattr(hub, ps._LAST_STATUS_STAMP_ATTR, status_stamp)
        phase = ps.pedestrian_display_phase(hub)

        if phase == "open" and getattr(hub, ps._DEADLINE_ATTR, None) is None:
            live_seen = bool(getattr(hub, ps._LIVE_SEEN_ATTR, False))

            if live_seen:
                # Dedicated position exists for this PED cycle, so direction
                # bits are not authoritative enough to display Closing.  We do
                # still count repeated closing statuses so a subsequent fresh
                # stopped/0% endpoint from an external app/remote can close the
                # overlay safely.
                if (
                    getattr(hub, "is_operating", None) is True
                    and getattr(hub, "movement", None) == "closing"
                ):
                    setattr(
                        hub,
                        ps._CLOSING_STATUS_COUNT_ATTR,
                        prior_status_count + 1,
                    )
                elif (
                    getattr(hub, "position", None) == 0
                    and getattr(hub, "is_operating", None) is False
                    and prior_status_count >= ps._CLOSING_CONFIRMATION_COUNT
                ):
                    ps.cancel_pedestrian_display_cycle(hub, notify=False)
                    _sync_phase_tracking(hub, None)
                    return
                else:
                    setattr(hub, ps._CLOSING_STATUS_COUNT_ATTR, 0)
            else:
                # Controllers with no useful dedicated position topic keep the
                # beta.16 repeated-status fallback.
                if ps._record_untimed_open_status(hub):
                    ps._transition_to_closing(hub)
                    phase = "closing"
                    _sync_phase_tracking(hub, phase)

        elif phase == "closing" and _fresh_status_can_finish_closing(hub, status_stamp):
            ps.cancel_pedestrian_display_cycle(hub, notify=False)
            _sync_phase_tracking(hub, None)
            return

    # Final fallback for status-only controllers already in closing.  Unlike
    # beta.16 this is scoped to the closing phase itself, not whether the PED
    # cycle happened to see a live position earlier during opening.
    phase = ps.pedestrian_display_phase(hub)
    if (
        phase == "closing"
        and not getattr(hub, _CLOSING_LIVE_SEEN_ATTR, False)
        and getattr(hub, "position", None) == 0
        and getattr(hub, "is_operating", None) is False
    ):
        ps.cancel_pedestrian_display_cycle(hub, notify=False)
        _sync_phase_tracking(hub, None)
