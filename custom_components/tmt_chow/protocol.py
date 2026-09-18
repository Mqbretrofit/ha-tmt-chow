"""Pure protocol helpers for TMT Chow status payloads."""

from __future__ import annotations

import json
import re
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

    battery_percent = (battery_raw & 0x7F) if battery_raw is not None else None
    # Some controllers report FF when no valid battery percentage is
    # available. Masking that byte gives 127, which must never be exposed as
    # a Home Assistant percentage. Treat any decoded value above 100 as
    # unavailable instead of inventing a percentage.
    if battery_percent is not None and battery_percent > 100:
        battery_percent = None

    return GateStatus(
        position=(position_raw & 0x7F) if position_raw is not None else None,
        is_operating=bool(flags & 0x40) if flags is not None else None,
        is_open_direction=bool(position_raw & 0x80) if position_raw is not None else None,
        battery_percent=battery_percent,
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


def unwrap_ouranos_uart_data(payload: str | None) -> str | None:
    """Return UART DATA text from raw, helper-wrapped or nested JSON payloads."""
    if not payload:
        return None

    data = payload.strip()
    # The native helper can hand Python a JSON string whose response field is
    # itself a serialized UART envelope. Decode a bounded number of layers
    # before protocol-specific parsing so escaped CR/LF never reaches tokens.
    for _ in range(3):
        try:
            envelope = json.loads(data)
        except (TypeError, ValueError):
            break

        if isinstance(envelope, str):
            data = envelope.strip()
            continue
        if not isinstance(envelope, dict):
            return None

        if "DATA" in envelope:
            if (
                str(envelope.get("CMD", "")).upper() != "UART"
                or envelope.get("RESULT") != 0
                or not isinstance(envelope.get("DATA"), str)
            ):
                return None
            data = envelope["DATA"].strip()
            continue

        response = envelope.get("response")
        if isinstance(response, str):
            data = response.strip()
            continue

        return None

    return data


def parse_ouranos_rs_response(payload: str | None) -> GateStatus | None:
    """Parse an OURANOS UART envelope containing an ACK RS status frame."""
    data = unwrap_ouranos_uart_data(payload)
    if data is None:
        return None

    marker = data.upper().find("ACK RS:")
    if marker < 0:
        return None
    ack = data[marker:]
    ack = re.split(r";src=", ack, maxsplit=1, flags=re.IGNORECASE)[0].strip()
    return parse_ack_rs(ack)


_OURANOS_STATUS_RE = re.compile(
    r"^ACK STATUS:(?P<state>[^,]+),(?P<position>-?\d+)\s*$",
    re.IGNORECASE,
)


def parse_ouranos_status_response(payload: str | None) -> tuple[str, GateStatus] | None:
    """Parse the APK-compatible PS19001 native ``ACK STATUS`` response."""
    if not payload:
        return None
    try:
        envelope = json.loads(payload)
    except (TypeError, ValueError):
        return None
    if (
        not isinstance(envelope, dict)
        or str(envelope.get("CMD", "")).upper() != "UART"
        or envelope.get("RESULT") != 0
        or not isinstance(envelope.get("DATA"), str)
    ):
        return None

    match = _OURANOS_STATUS_RE.match(envelope["DATA"].strip())
    if match is None:
        return None
    state = " ".join(match.group("state").upper().split())
    position = int(match.group("position"))
    if not 0 <= position <= 100:
        return None

    if "OPENING" in state:
        operating = True
        open_direction: bool | None = True
    elif "CLOSING" in state or "CLOSEING" in state:
        operating = True
        open_direction = False
    elif "STOPPED" in state:
        operating = False
        open_direction = None
    elif "OPENED" in state:
        operating = False
        open_direction = True
    elif "CLOSED" in state:
        operating = False
        open_direction = False
    else:
        return None

    return state, GateStatus(
        position=position,
        is_operating=operating,
        is_open_direction=open_direction,
        battery_percent=None,
    )


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
