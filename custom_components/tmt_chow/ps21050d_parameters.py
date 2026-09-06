"""APK-derived 20-value parameter support for live PS21050D hardware."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Final

from .model_parameter_schemas import parameter_options, parameter_schema_for

CONTROLLER_TYPE: Final = "PS21050D"
APP_MODEL: Final = "PS21050"
# Android product-class protocol selector. The live Shadow field UART VER may
# independently report 2; that is controller runtime metadata, not this flag.
UART_VERSION: Final = 1
PARAMETER_COUNT: Final = 20

_WIRE_KEYS: Final = (
    "func_system_learn_method",
    "func_open_over_current",
    "func_close_over_current",
    "func_open_speed",
    "func_close_speed",
    "function_slow_speed_setting",
    "func_slow_down_point",
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
)


class PS21050DParameterError(ValueError):
    """The PS21050D parameter frame cannot be mapped safely."""


def _extract_app_layout() -> tuple[tuple, tuple, tuple]:
    """Return the app's exact 20 wire specs plus normal/Hall current helpers."""
    schema = parameter_schema_for(APP_MODEL)
    if schema is None:
        raise RuntimeError("The APK-derived PS21050 schema is missing")

    keys = tuple(spec[1] for spec in schema)
    start = -1
    for index in range(0, len(schema) - PARAMETER_COUNT + 1):
        if keys[index : index + PARAMETER_COUNT] == _WIRE_KEYS:
            start = index
            break
    if start < 0:
        raise RuntimeError("The APK-derived PS21050 20-value wire layout changed")

    wire = tuple(schema[start : start + PARAMETER_COUNT])
    prefix = tuple(schema[:start])

    normal_helpers = tuple(
        spec
        for spec in prefix
        if spec[1] == "func_open_over_current"
        and spec[2] == "option_over_current_setting_p190"
    )
    hall_helpers = tuple(
        spec
        for spec in prefix
        if spec[1] == "func_open_over_current"
        and spec[2] == "option_over_current_setting_p190_hall"
    )
    if len(normal_helpers) != 1 or len(hall_helpers) != 1:
        raise RuntimeError("The APK-derived PS21050 current helper layout changed")

    return wire, normal_helpers[0], hall_helpers[0]


APP_PARAMETERS, _NORMAL_CURRENT_SPEC, _HALL_CURRENT_SPEC = _extract_app_layout()

RAW_PARAMETERS: Final = tuple(
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
PARAMETERS: Final = RAW_PARAMETERS

_RP_RE = re.compile(r"(?:^|\b)ACK RP(?:,1)?:([^;\r\n]+)")


def parse_parameter_response(payload: str) -> tuple[int, ...] | None:
    """Parse the exact 20-value PS21050/PS21050D RP,1 or DEV PARAM frame."""
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


def _current_spec(values: Sequence[int] | None) -> tuple:
    motor_mode = (
        int(values[0])
        if values and len(values) >= 1
        else int(APP_PARAMETERS[0][5] or 0)
    )
    return _HALL_CURRENT_SPEC if motor_mode == 2 else _NORMAL_CURRENT_SPEC


def parameter_options_for(index: int, values: Sequence[int] | None = None) -> tuple[str, ...]:
    if not 0 <= index < PARAMETER_COUNT:
        return ()
    spec = _current_spec(values) if index in (1, 2) else APP_PARAMETERS[index]
    return tuple(parameter_options(spec))


def wire_value_to_option(index: int, value: int, values: Sequence[int] | None = None) -> str | None:
    options = parameter_options_for(index, values)
    if not options:
        return None
    spec = _current_spec(values) if index in (1, 2) else APP_PARAMETERS[index]
    logical = int(value) - int(spec[6] or 0)
    return options[logical] if 0 <= logical < len(options) else None


def option_to_wire_value(index: int, option: str, values: Sequence[int] | None = None) -> int:
    options = parameter_options_for(index, values)
    try:
        logical = options.index(option)
    except ValueError as err:
        raise PS21050DParameterError("Unsupported PS21050D parameter option") from err
    spec = _current_spec(values) if index in (1, 2) else APP_PARAMETERS[index]
    return logical + int(spec[6] or 0)


def validate_wire_values(values: Sequence[int]) -> tuple[int, ...]:
    if not _wire_values_are_valid_shape(values):
        raise PS21050DParameterError("PS21050D requires exactly 20 byte-sized parameter values")
    normalized = tuple(int(value) for value in values)
    for index, value in enumerate(normalized):
        if wire_value_to_option(index, value, normalized) is None:
            raise PS21050DParameterError(
                f"PS21050D parameter {index + 1} is outside the active app option range"
            )
    return normalized


def encode_parameter_write(values: Sequence[int]) -> str:
    normalized = validate_wire_values(values)
    return "WP,1:" + ",".join(map(str, normalized))
