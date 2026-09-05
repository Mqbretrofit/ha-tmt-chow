"""Live-captured read-only parameter support for PS21050D."""

from __future__ import annotations

import re
from typing import Final

CONTROLLER_TYPE: Final = "PS21050D"
PARAMETER_COUNT: Final = 20

# The live controller reports exactly 20 values in both DEV PARAM and ACK RP,1.
# Their vendor UI meaning is not verified yet, so every entry is intentionally
# parameter_type 4 (non-editable) and exposed only through diagnostics/runtime
# state.  This keeps the capture useful without permitting speculative writes.
PARAMETERS: Final = tuple(
    (
        "n",
        f"ps21050d_raw_{index:02d}",
        None,
        4,
        0,
        0,
        0,
        255,
        None,
        None,
        None,
        0,
        255,
        1,
        1.0,
        None,
        None,
    )
    for index in range(1, PARAMETER_COUNT + 1)
)

_RP_RE = re.compile(r"(?:^|\b)ACK RP(?:,1)?:([^;\r\n]+)")


def parse_parameter_response(payload: str) -> tuple[int, ...] | None:
    """Parse the exact 20-value PS21050D read response or DEV PARAM body."""
    if not isinstance(payload, str):
        return None

    clean = payload.strip()
    if not clean:
        return None

    match = _RP_RE.search(clean)
    if match:
        body = match.group(1)
    else:
        # Shadow DEV PARAM already contains only the CSV body.  Do not treat an
        # unrelated ACK/NAK as parameter data.
        if "ACK " in clean or "NAK " in clean:
            return None
        body = clean.split(";", 1)[0].lstrip(":")

    tokens = [token.strip() for token in body.split(",")]
    if len(tokens) != PARAMETER_COUNT or any(token == "" for token in tokens):
        return None

    try:
        values = tuple(int(token, 10) for token in tokens)
    except ValueError:
        return None

    if any(value < 0 or value > 255 for value in values):
        return None
    return values
