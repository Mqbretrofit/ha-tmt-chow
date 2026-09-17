"""Live-verified PS22087 account / PS22087B (P710U) parameter profile."""

from __future__ import annotations

from dataclasses import dataclass
import re
from collections.abc import Sequence

APP_MODEL = "PS22087"
CONTROLLER_TYPE = "PS22087B"
HARDWARE_MODEL = "P710U"
PARAMETER_COUNT = 15


@dataclass(slots=True, frozen=True)
class P710UParameterDefinition:
    """One field in the verified F1..F9,A..F wire frame."""

    code: str
    name: str
    options: tuple[str, ...]
    writable: bool = True


# The controller returns two undocumented/reserved fields (B and D). They must
# remain in the full frame and are therefore exposed read-only and preserved
# verbatim during every write.
PARAMETERS: tuple[P710UParameterDefinition, ...] = (
    P710UParameterDefinition("F1", "Deceleration trigger distance", ("75%", "80%", "85%", "90%", "95%")),
    P710UParameterDefinition("F2", "Full-open remote button", ("Disabled", "Button A", "Button B", "Button C", "Button D")),
    P710UParameterDefinition("F3", "Integrated-light remote button", ("Disabled", "Button A", "Button B", "Button C", "Button D")),
    P710UParameterDefinition("F4", "External-control remote button", ("Disabled", "Button A", "Button B", "Button C", "Button D")),
    P710UParameterDefinition("F5", "Photocell activation", ("Disabled", "Enabled", "Enabled on closing only")),
    P710UParameterDefinition("F6", "Buzzer alarm", ("Disabled", "Enabled")),
    P710UParameterDefinition("F7", "Automatic closing", ("Disabled", "30 seconds", "60 seconds", "90 seconds", "120 seconds", "150 seconds", "180 seconds", "210 seconds", "240 seconds")),
    P710UParameterDefinition("F8", "Integrated light duration", ("Disabled", "1 minute", "2 minutes", "3 minutes")),
    P710UParameterDefinition("F9", "Overcurrent reaction", ("Stop", "Opening: stop / Closing: reverse 10 cm", "Full reverse")),
    P710UParameterDefinition("A", "Overcurrent adjustment", ("+0.2 A", "+0.4 A", "+0.6 A", "+0.8 A", "+1.0 A", "+1.2 A", "+1.4 A", "+1.6 A", "+1.8 A")),
    P710UParameterDefinition("B", "Function B (undocumented)", (), writable=False),
    P710UParameterDefinition("C", "Opening current limit", ("2 A", "3 A", "4 A", "5 A", "6 A", "7 A", "8 A")),
    P710UParameterDefinition("D", "Function D (undocumented)", (), writable=False),
    P710UParameterDefinition("E", "Closing current limit", ("2 A", "3 A", "4 A", "5 A", "6 A", "7 A", "8 A")),
    P710UParameterDefinition("F", "+24 V terminal power", ("Continuous power", "Standby mode")),
)

_RP_RE = re.compile(r"(?:^|\b)ACK RP,1:([^;\r\n]+)")


class PS22087BParameterError(ValueError):
    """The PS22087B parameter frame is invalid or unsafe to encode."""


def parse_parameter_response(payload: str) -> tuple[int, ...] | None:
    """Parse the exact live 15-value RP,1 response."""
    match = _RP_RE.search(payload)
    if not match:
        return None
    try:
        values = tuple(int(item.strip()) for item in match.group(1).split(","))
    except ValueError:
        return None
    if len(values) != PARAMETER_COUNT or not all(0 <= value <= 255 for value in values):
        return None
    return values


def validate_requested_value(index: int, value: int) -> None:
    """Reject reserved fields and values outside the verified UI table."""
    if not 0 <= index < PARAMETER_COUNT:
        raise PS22087BParameterError("PS22087B parameter index is outside the wire frame")
    definition = PARAMETERS[index]
    if not definition.writable or not 0 <= int(value) < len(definition.options):
        raise PS22087BParameterError("Unsupported PS22087B parameter value")


def encode_parameter_write(values: Sequence[int]) -> str:
    """Build one complete WP,1 frame while retaining reserved B/D values."""
    normalized = tuple(int(value) for value in values)
    if len(normalized) != PARAMETER_COUNT or not all(0 <= value <= 255 for value in normalized):
        raise PS22087BParameterError("PS22087B requires exactly 15 byte-sized values")
    return "WP,1:" + ",".join(str(value) for value in normalized)
