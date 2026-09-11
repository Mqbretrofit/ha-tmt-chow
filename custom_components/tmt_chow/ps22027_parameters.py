"""Read-only PS22027 20-value parameter mapping derived from the vendor APK."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Final

from .model_parameter_schemas import parameter_name, parameter_options, parameter_schema_for

CONTROLLER_TYPE: Final = "PS22027"
PARAMETER_COUNT: Final = 20
HALL_MODE: Final = 2

_WIRE_KEYS: Final = (
    "func_slide_gate_operation_mode",
    "func_open_over_current",
    "func_close_over_current",
    "func_open_speed",
    "func_close_speed",
    "function_slow_speed_setting",
    "func_open_delay",
    "func_close_delay",
    "func_auto_closing",
    "func_photocell",
    "func_pedestrian_mode",
    "function_alert_light",
    "func_ph1",
    "func_ph2",
    "func_alarm_buzzer",
    "func_electronic_locker",
    "func_led_direction",
    "func_single_door",
    "func_close_limit_reaction_time",
    "func_overcurrent_sensitivity",
)

_RP_RE = re.compile(r"(?:^|\b)ACK RP(?:,1)?:([^;\r\n]+)")


class PS22027ParameterError(ValueError):
    """The PS22027 parameter frame cannot be mapped safely."""


def _extract_app_layout() -> tuple[tuple, tuple, tuple]:
    """Return the live 20-slot layout plus the APK P190 Hall-current helpers.

    The generated PS22027 schema contains two inherited P190 current helper
    entries before the controller's real 20 wire slots. Live hardware proved
    that those helper entries are not separate RP,1 fields.
    """
    schema = parameter_schema_for(CONTROLLER_TYPE)
    if schema is None:
        raise RuntimeError("The APK-derived PS22027 schema is missing")

    keys = tuple(spec[1] for spec in schema)
    start = next(
        (
            index
            for index in range(len(schema) - PARAMETER_COUNT + 1)
            if keys[index : index + PARAMETER_COUNT] == _WIRE_KEYS
        ),
        -1,
    )
    if start < 0:
        raise RuntimeError("The APK-derived PS22027 20-value wire layout changed")

    prefix = tuple(schema[:start])
    if (
        len(prefix) != 2
        or tuple(spec[1] for spec in prefix)
        != ("func_open_over_current", "func_close_over_current")
        or any(spec[2] != "option_over_current_setting_p190" for spec in prefix)
    ):
        raise RuntimeError("The PS22027 inherited current-helper prefix changed")

    p190_schema = parameter_schema_for("P190U")
    if p190_schema is None:
        raise RuntimeError("The APK-derived P190U helper schema is missing")

    hall_open = [
        spec
        for spec in p190_schema
        if spec[1] == "func_open_over_current"
        and spec[2] == "option_over_current_setting_p190_hall"
    ]
    hall_close = [
        spec
        for spec in p190_schema
        if spec[1] == "func_close_over_current"
        and spec[2] == "option_over_current_setting_p190_hall"
    ]
    if len(hall_open) != 1 or len(hall_close) != 1:
        raise RuntimeError("The APK-derived P190 Hall-current helper layout changed")

    return tuple(schema[start : start + PARAMETER_COUNT]), hall_open[0], hall_close[0]


APP_PARAMETERS, _HALL_OPEN_CURRENT_SPEC, _HALL_CLOSE_CURRENT_SPEC = _extract_app_layout()


def parse_parameter_response(payload: str) -> tuple[int, ...] | None:
    """Parse an exact 20-value PS22027 RP,1 response without enabling writes."""
    if not isinstance(payload, str):
        return None
    clean = payload.strip()
    if not clean:
        return None

    match = _RP_RE.search(clean)
    if match:
        body = match.group(1)
    else:
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
    return values if _wire_values_are_valid_shape(values) else None


def _wire_values_are_valid_shape(values: Sequence[int]) -> bool:
    return len(values) == PARAMETER_COUNT and all(
        isinstance(value, int) and 0 <= value <= 255 for value in values
    )


def _active_spec(index: int, values: Sequence[int] | None = None) -> tuple:
    if not 0 <= index < PARAMETER_COUNT:
        raise PS22027ParameterError("PS22027 parameter index is outside the wire frame")

    mode = int(values[0]) if values and len(values) == PARAMETER_COUNT else None
    if mode == HALL_MODE and index == 1:
        return _HALL_OPEN_CURRENT_SPEC
    if mode == HALL_MODE and index == 2:
        return _HALL_CLOSE_CURRENT_SPEC
    return APP_PARAMETERS[index]


def parameter_options_for(
    index: int, values: Sequence[int] | None = None
) -> tuple[str, ...]:
    """Return vendor UI options, switching the two current slots in Hall mode."""
    if not 0 <= index < PARAMETER_COUNT:
        return ()
    return tuple(parameter_options(_active_spec(index, values)))


def wire_value_to_option(
    index: int, value: int, values: Sequence[int] | None = None
) -> str | None:
    """Convert one raw wire byte to the label shown by the vendor UI."""
    if not 0 <= index < PARAMETER_COUNT:
        return None
    spec = _active_spec(index, values)
    options = tuple(parameter_options(spec))
    if not options:
        return None
    logical = int(value) - int(spec[6] or 0)
    return options[logical] if 0 <= logical < len(options) else None


def decoded_parameter_values(values: Sequence[int] | None) -> list[dict[str, object]] | None:
    """Return diagnostic-only raw/display mapping for the observed 20-value frame."""
    if values is None or not _wire_values_are_valid_shape(values):
        return None

    normalized = tuple(int(value) for value in values)
    decoded: list[dict[str, object]] = []
    for index, (spec, raw) in enumerate(zip(APP_PARAMETERS, normalized, strict=True)):
        active_spec = _active_spec(index, normalized)
        decoded.append(
            {
                "index": index + 1,
                "key": spec[1],
                "name": parameter_name(spec),
                "raw": raw,
                "display": wire_value_to_option(index, raw, normalized),
                "mapping_option_key": active_spec[2],
                "mapping_offset": int(active_spec[6] or 0),
                "mapping_source": (
                    "p190_hall_current"
                    if normalized[0] == HALL_MODE and index in (1, 2)
                    else "ps22027_app"
                ),
            }
        )
    return decoded
