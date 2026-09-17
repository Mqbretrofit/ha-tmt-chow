"""Verified PS25007/PS25007A 17-slot RP,1/WP,1 parameter profile."""

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
    """The PS25007A parameter frame is invalid or unsafe to encode."""


def validate_wire_values(values: Sequence[int]) -> tuple[int, ...]:
    """Validate the complete 17-slot raw option-index vector."""
    normalized = tuple(int(value) for value in values)
    if len(normalized) != PARAMETER_COUNT:
        raise PS25007AParameterError(
            f"PS25007A parameter count mismatch: expected {PARAMETER_COUNT}, "
            f"got {len(normalized)}"
        )
    if len(PARAMETERS) != PARAMETER_COUNT:
        raise PS25007AParameterError("Internal PS25007A definition mismatch")
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
        body = clean.split(";", 1)[0]
    try:
        return validate_wire_values(tuple(int(item.strip()) for item in body.split(",")))
    except (TypeError, ValueError, PS25007AParameterError):
        return None


def encode_parameter_write(values: Sequence[int]) -> str:
    """Build exactly one complete PS25007A WP,1 frame."""
    normalized = validate_wire_values(values)
    return "WP,1:" + ",".join(str(value) for value in normalized)
