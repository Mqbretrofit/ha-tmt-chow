"""PS21053/PS21053C parameter definitions verified from TMT Chow 3.1.4."""

from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(slots=True, frozen=True)
class ParameterDefinition:
    """One indexed PS21053 parameter and its stable Home Assistant option keys."""

    key: str
    options: tuple[str, ...]


PARAMETERS: tuple[ParameterDefinition, ...] = (
    ParameterDefinition("operation_direction", ("default", "reversed")),
    ParameterDefinition(
        "automatic_closing",
        (
            "off",
            "seconds_5",
            "seconds_15",
            "seconds_30",
            "seconds_45",
            "seconds_60",
            "seconds_80",
            "seconds_120",
            "seconds_180",
        ),
    ),
    ParameterDefinition("safety_device_mode", ("mode_1", "mode_2", "mode_3")),
    ParameterDefinition(
        "operation_speed",
        (
            "operation_50_learning_50",
            "operation_70_learning_60",
            "operation_85_learning_70",
            "operation_100_learning_80",
        ),
    ),
    ParameterDefinition(
        "deceleration_point",
        ("percent_75", "percent_80", "percent_85", "percent_90", "percent_95"),
    ),
    ParameterDefinition(
        "deceleration_speed",
        ("percent_80", "percent_60", "percent_40", "percent_25"),
    ),
    ParameterDefinition(
        "overcurrent", tuple(f"amp_{value}" for value in range(2, 14))
    ),
    ParameterDefinition(
        "pedestrian_mode",
        ("seconds_3", "seconds_6", "seconds_9", "seconds_12", "seconds_15", "seconds_18"),
    ),
    ParameterDefinition("flashing_light", ("off", "on")),
    ParameterDefinition(
        "overcurrent_reaction",
        (
            "stop",
            "reverse_1s_then_stop",
            "reverse_3s_then_stop",
            "reverse_to_end",
        ),
    ),
    ParameterDefinition("main_operation_key", ("key_a", "key_b", "key_c", "key_d")),
    ParameterDefinition(
        "pedestrian_key", ("no_function", "key_a", "key_b", "key_c", "key_d")
    ),
    ParameterDefinition(
        "external_device_key", ("no_function", "key_a", "key_b", "key_c", "key_d")
    ),
    ParameterDefinition("photocell_activation", ("off", "on")),
    ParameterDefinition("photocell_2_activation", ("off", "on")),
    ParameterDefinition("stop_terminal", ("off", "on")),
    ParameterDefinition(
        "gate_operation", ("open_stop_close_stop", "open_stop_close")
    ),
)


_RP_RE = re.compile(r"(?:^|\b)ACK RP,1:([^;\r\n]+)")


def parse_parameter_response(payload: str) -> tuple[int, ...] | None:
    """Parse and strictly validate an ACK RP,1 response."""
    match = _RP_RE.search(payload)
    if not match:
        return None
    try:
        values = tuple(int(item.strip()) for item in match.group(1).split(","))
    except ValueError:
        return None
    return values if validate_parameter_values(values) else None


def validate_parameter_values(values: tuple[int, ...]) -> bool:
    """Return whether every value is allowed by the exact product definition."""
    return len(values) == len(PARAMETERS) and all(
        0 <= value < len(definition.options)
        for definition, value in zip(PARAMETERS, values, strict=True)
    )


def encode_parameter_write(values: tuple[int, ...]) -> str:
    """Build the UART-v1 full parameter write command."""
    if not validate_parameter_values(values):
        raise ValueError("Invalid PS21053 parameter set")
    return "WP,1:" + ",".join(str(value) for value in values)
