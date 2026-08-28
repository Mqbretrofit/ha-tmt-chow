"""Pure protocol helpers for TMT Chow status payloads."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True, frozen=True)
class GateStatus:
    """Decoded first gate status."""

    position: int | None
    is_operating: bool | None
    is_open_direction: bool | None
    battery_percent: int | None


def _hex_byte(value: str) -> int | None:
    try:
        parsed = int(value.strip(), 16)
    except (TypeError, ValueError):
        return None
    return parsed if 0 <= parsed <= 255 else None


def decode_dev_status(payload: str | None) -> GateStatus:
    """Decode DEV STATUS using the same bit mapping as Wbt01Connection."""
    if not payload:
        return GateStatus(None, None, None, None)
    fields = payload.split(";", 1)[0].split(",")
    if len(fields) < 4:
        return GateStatus(None, None, None, None)

    battery_raw = _hex_byte(fields[1])
    flags = _hex_byte(fields[2])
    position_raw = _hex_byte(fields[3])
    return GateStatus(
        position=(position_raw & 0x7F) if position_raw is not None else None,
        is_operating=bool(flags & 0x40) if flags is not None else None,
        is_open_direction=bool(position_raw & 0x80) if position_raw is not None else None,
        battery_percent=(battery_raw & 0x7F) if battery_raw is not None else None,
    )


def parse_position(payload: str | None) -> int | None:
    """Parse the dedicated /position percentage payload."""
    if payload is None:
        return None
    try:
        value = int(payload.strip().removesuffix("%"))
    except ValueError:
        return None
    return max(0, min(100, value))


def parse_ack_rs(payload: str | None) -> GateStatus | None:
    """Parse ACK RS:<DEV STATUS> emitted during gate movement."""
    if not payload or not payload.startswith("ACK RS:"):
        return None
    return decode_dev_status(payload.removeprefix("ACK RS:"))


def extract_shadow_reported(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Extract reported state from Shadow GET or update/documents payload."""
    state = payload.get("state")
    if isinstance(state, dict):
        reported = state.get("reported")
        if isinstance(reported, dict):
            return reported

    current = payload.get("current")
    if isinstance(current, dict):
        state = current.get("state")
        if isinstance(state, dict):
            reported = state.get("reported")
            if isinstance(reported, dict):
                return reported
    return None
