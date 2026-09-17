"""Live-verified 19-value UART0 parameter support for PS19001."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Final

from .model_parameter_schemas import parameter_options, parameter_schema_for

CONTROLLER_TYPE: Final = "PS19001"
PARAMETER_COUNT: Final = 19
HALL_MODE: Final = 2
WIRE_IDS: Final = "123456789ABCDEFGHIJ"

_WIRE_KEYS: Final = (
    "func_system_learn_method",
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
)

_ACK_RE = re.compile(
    r"(?:^|[^A-Z])ACK READ FUNCTION(?P<body>"
    + "".join(rf",{field_id}:[^,;\r\n]+" for field_id in WIRE_IDS)
    + r")"
)


class PS19001ParameterError(ValueError):
    """The PS19001 parameter frame cannot be mapped safely."""


def _extract_app_layout() -> tuple[tuple, tuple, tuple]:
    """Remove four inherited current helpers that are not wire fields.

    P190U.getParameterStart() returns 1. Its first four generated entries are
    the normal/Hall current lookup helpers used when the motor-mode field
    changes. Real PS19001 hardware confirms that the actual frame is the next
    19 entries, labelled 1 through J.
    """
    schema = parameter_schema_for(CONTROLLER_TYPE)
    if schema is None:
        raise RuntimeError("The APK-derived PS19001 schema is missing")
    keys = tuple(spec[1] for spec in schema)
    start = next(
        (
            index
            for index in range(len(schema) - PARAMETER_COUNT + 1)
            if keys[index : index + PARAMETER_COUNT] == _WIRE_KEYS
        ),
        -1,
    )
    if start != 4:
        raise RuntimeError("The APK-derived PS19001 19-value wire layout changed")

    prefix = tuple(schema[:start])
    normal = [
        spec
        for spec in prefix
        if spec[1] == "func_open_over_current"
        and spec[2] == "option_over_current_setting_p190"
    ]
    hall = [
        spec
        for spec in prefix
        if spec[1] == "func_open_over_current"
        and spec[2] == "option_over_current_setting_p190_hall"
    ]
    if len(normal) != 1 or len(hall) != 1:
        raise RuntimeError("The APK-derived PS19001 current helpers changed")
    return tuple(schema[start : start + PARAMETER_COUNT]), normal[0], hall[0]


APP_PARAMETERS, _NORMAL_CURRENT_SPEC, _HALL_CURRENT_SPEC = _extract_app_layout()


def _active_spec(index: int, values: Sequence[int] | None = None) -> tuple:
    if not 0 <= index < PARAMETER_COUNT:
        raise PS19001ParameterError("PS19001 parameter index is outside the wire frame")
    mode = int(values[0]) if values else None
    if index in (1, 2):
        return _HALL_CURRENT_SPEC if mode == HALL_MODE else _NORMAL_CURRENT_SPEC
    return APP_PARAMETERS[index]


def _extract_response_body(payload: str) -> str | None:
    clean = payload.strip()
    if not clean:
        return None
    try:
        envelope = json.loads(clean)
    except (json.JSONDecodeError, TypeError):
        envelope = None
    if isinstance(envelope, dict):
        if envelope.get("RESULT") != 0 or not isinstance(envelope.get("DATA"), str):
            return None
        clean = envelope["DATA"].strip()

    match = _ACK_RE.search(clean)
    if match is not None:
        return match.group("body")
    if "ACK " in clean or "NAK " in clean:
        return None
    return clean.split(";", 1)[0]


def parse_parameter_response(payload: str) -> tuple[int, ...] | None:
    """Parse only an exact PS19001 field-labelled 1..J response."""
    if not isinstance(payload, str):
        return None
    body = _extract_response_body(payload)
    if body is None:
        return None
    tokens = body.lstrip(",").split(",")
    if len(tokens) != PARAMETER_COUNT:
        return None

    raw_tokens: list[str] = []
    for expected_id, token in zip(WIRE_IDS, tokens, strict=True):
        field_id, separator, raw = token.partition(":")
        if field_id != expected_id or separator != ":" or not raw:
            return None
        raw_tokens.append(raw)

    try:
        mode_spec = APP_PARAMETERS[0]
        mode_raw = int(raw_tokens[0], 10)
        mode = mode_raw - int(mode_spec[6] or 0)
        logical_values: list[int] = []
        for index, raw in enumerate(raw_tokens):
            spec = _active_spec(index, (mode,))
            base = 10 if int(spec[3] or 0) == 1 else 16
            logical_values.append(int(raw, base) - int(spec[6] or 0))
        logical = tuple(logical_values)
        return validate_parameter_values(logical)
    except (PS19001ParameterError, ValueError):
        return None


def parameter_options_for(
    index: int, values: Sequence[int] | None = None
) -> tuple[str, ...]:
    if not 0 <= index < PARAMETER_COUNT:
        return ()
    return tuple(parameter_options(_active_spec(index, values)))


def logical_value_to_option(
    index: int, value: int, values: Sequence[int] | None = None
) -> str | None:
    options = parameter_options_for(index, values)
    return options[int(value)] if 0 <= int(value) < len(options) else None


def option_to_logical_value(
    index: int, option: str, values: Sequence[int] | None = None
) -> int:
    options = parameter_options_for(index, values)
    try:
        return options.index(option)
    except ValueError as err:
        raise PS19001ParameterError("Unsupported PS19001 parameter option") from err


def validate_parameter_values(values: Sequence[int]) -> tuple[int, ...]:
    if len(values) != PARAMETER_COUNT:
        raise PS19001ParameterError(
            "PS19001 requires exactly 19 logical parameter values"
        )
    normalized = tuple(int(value) for value in values)
    for index, value in enumerate(normalized):
        options = parameter_options_for(index, normalized)
        if not 0 <= value < len(options):
            raise PS19001ParameterError(
                f"PS19001 parameter {index + 1} is outside the active app option range"
            )
    return normalized


def _format_wire_value(spec: tuple, value: int) -> str:
    if int(spec[3] or 0) == 1:
        return str(value)
    maximum = int(spec[7] or 0)
    width = max(1, len(str(maximum)))
    return f"{value:0{width}X}" if width > 1 else str(value)


def encode_parameter_write(values: Sequence[int]) -> str:
    """Build the exact full WRITE FUNCTION,1..J frame."""
    normalized = validate_parameter_values(values)
    fields: list[str] = []
    for index, (field_id, value) in enumerate(
        zip(WIRE_IDS, normalized, strict=True)
    ):
        spec = _active_spec(index, normalized)
        wire_value = value + int(spec[6] or 0)
        fields.append(f"{field_id}:{_format_wire_value(spec, wire_value)}")
    return "WRITE FUNCTION," + ",".join(fields)
