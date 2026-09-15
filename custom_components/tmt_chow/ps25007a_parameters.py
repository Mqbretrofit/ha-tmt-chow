"""Verified PS25007/PS25007A 17-slot RP,1/WP,1 parameter profile.

The TMT account API identifies this controller as PS25007 while live DEV INFO
reports PS25007A.  The PS25007 AutoProduct Proposal exposes the same 17
parameter positions and option counts as the already verified P500BU
PS21053/PS21053C profile.  Real PS25007A hardware confirmed the order by
changing F7/Overcurrent and observing wire slot 7, including the full 2 A to
13 A option range.

This module intentionally keeps the concrete PS25007A identity separate.  It
reuses only the verified 17-slot option definitions; pedestrian command safety
is handled independently and direct PED OPEN remains hard-blocked.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from .parameters import PARAMETERS

APP_MODEL = "PS25007"
CONTROLLER_TYPE = "PS25007A"
REFERENCE_SCHEMA_MODEL = "PS21053"
PARAMETER_COUNT = 17

# Option counts from the PS25007 AutoProduct Proposal, in F1..FP wire order.
PROPOSAL_OPTION_COUNTS = (2, 9, 3, 4, 5, 4, 12, 6, 2, 4, 4, 5, 5, 2, 2, 2, 2)

_RP_RE = re.compile(r"(?:^|\b)ACK RP(?:,1)?:([^;\r\n]+)")


class PS25007AParameterError(ValueError):
    """The PS25007A parameter frame is invalid or cannot be written safely."""


def validate_wire_values(values: Sequence[int]) -> tuple[int, ...]:
    """Validate the complete 17-slot raw option-index vector."""
    normalized = tuple(int(value) for value in values)
    if len(normalized) != PARAMETER_COUNT:
        raise PS25007AParameterError(
            f"PS25007A parameter count mismatch: expected {PARAMETER_COUNT}, "
            f"got {len(normalized)}"
        )

    if len(PARAMETERS) != PARAMETER_COUNT:
        raise PS25007AParameterError("Internal PS25007A parameter definition mismatch")

    for index, (definition, value) in enumerate(
        zip(PARAMETERS, normalized, strict=True)
    ):
        if not 0 <= value < len(definition.options):
            raise PS25007AParameterError(
                f"PS25007A parameter {index + 1} is outside its option range"
            )
    return normalized


def parse_parameter_response(payload: str) -> tuple[int, ...] | None:
    """Parse either ACK RP,1 telemetry or the raw Shadow DEV PARAM body."""
    if not isinstance(payload, str):
        return None

    clean = payload.strip()
    if not clean or clean.startswith("NAK"):
        return None

    match = _RP_RE.search(clean)
    if match:
        body = match.group(1)
    elif "ACK " in clean:
        return None
    else:
        # Shadow DEV PARAM contains only the comma-separated body.
        body = clean.split(";", 1)[0]

    try:
        values = tuple(int(item.strip()) for item in body.split(","))
        return validate_wire_values(values)
    except (TypeError, ValueError, PS25007AParameterError):
        return None


def encode_parameter_write(values: Sequence[int]) -> str:
    """Build exactly one complete PS25007A WP,1 frame."""
    normalized = validate_wire_values(values)
    return "WP,1:" + ",".join(str(value) for value in normalized)
