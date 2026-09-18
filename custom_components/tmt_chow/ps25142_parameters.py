"""PS25142 Proposal-B UART V3.0 18-slot parameter profile.

The wire order and option counts come directly from the controller's vendor
Proposal payload (F1..FP plus Fr).  UART V3.0 AutoProduct uses RP,1 / WP,1 and
transmits logical option indexes as one complete comma-separated frame.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from .parameters import PARAMETERS, ParameterDefinition

CONTROLLER_TYPE = "PS25142"
PARAMETER_COUNT = 18

PS25142_PARAMETERS: tuple[ParameterDefinition, ...] = PARAMETERS + (
    ParameterDefinition("power_saving_mode", ("off", "on")),
)

# Exact Proposal-B option counts in wire order:
# F1,F2,F3,F4,F5,F6,F7,F8,F9,FA,FC,FE,FF,FH,FJ,FL,FP,Fr.
PROPOSAL_OPTION_COUNTS = (2, 9, 3, 4, 5, 4, 12, 6, 2, 4, 4, 5, 5, 2, 2, 2, 2, 2)

_RP_RE = re.compile(r"(?:^|\b)ACK RP(?:,1)?:([^;\r\n\"}]+)")


class PS25142ParameterError(ValueError):
    """The PS25142 parameter frame is invalid or unsafe to encode."""


def validate_wire_values(values: Sequence[int]) -> tuple[int, ...]:
    """Validate the complete 18-slot logical option-index vector."""
    normalized = tuple(int(value) for value in values)
    if len(normalized) != PARAMETER_COUNT:
        raise PS25142ParameterError(
            f"PS25142 parameter count mismatch: expected {PARAMETER_COUNT}, "
            f"got {len(normalized)}"
        )
    if len(PS25142_PARAMETERS) != PARAMETER_COUNT:
        raise PS25142ParameterError("Internal PS25142 definition mismatch")
    if tuple(len(item.options) for item in PS25142_PARAMETERS) != PROPOSAL_OPTION_COUNTS:
        raise PS25142ParameterError("PS25142 Proposal definition mismatch")
    for index, (definition, value) in enumerate(
        zip(PS25142_PARAMETERS, normalized, strict=True)
    ):
        if not 0 <= value < len(definition.options):
            raise PS25142ParameterError(
                f"PS25142 parameter {index + 1} is outside its option range"
            )
    return normalized


def parse_parameter_response(payload: str) -> tuple[int, ...] | None:
    """Parse ACK RP,1 telemetry or an already extracted raw 18-slot body."""
    if not isinstance(payload, str):
        return None
    clean = payload.strip()
    if not clean or "NAK " in clean:
        return None
    match = _RP_RE.search(clean)
    if match:
        body = match.group(1)
    elif "ACK " in clean:
        return None
    else:
        body = clean.split(";", 1)[0].strip()
    try:
        values = tuple(int(item.strip()) for item in body.split(","))
        return validate_wire_values(values)
    except (TypeError, ValueError, PS25142ParameterError):
        return None


def encode_parameter_write(values: Sequence[int]) -> str:
    """Build exactly one complete PS25142 WP,1 frame."""
    normalized = validate_wire_values(values)
    return "WP,1:" + ",".join(str(value) for value in normalized)
