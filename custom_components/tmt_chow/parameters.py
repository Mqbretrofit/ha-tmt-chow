"""TMT Chow parameter definitions and RP/WP codecs."""

from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(slots=True, frozen=True)
class ParameterDefinition:
    """One indexed parameter and its Home Assistant options."""

    key: str
    options: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class P710UParameterDefinition:
    """One indexed P710U/PS22087B parameter."""

    code: str
    name: str
    options: tuple[str, ...]
    writable: bool = True


# Verified PS21053 / PS21053C 17-value profile.
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
        ("stop", "reverse_1s_then_stop", "reverse_3s_then_stop", "reverse_to_end"),
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
    ParameterDefinition("gate_operation", ("open_stop_close_stop", "open_stop_close")),
)


# P710U / PS22087B uses RP,1 / WP,1 too, but with 15 values.
# The positions below match the controller's F1..F9,A,B,C,D,E,F sequence.
# B and D are returned by the controller but are not documented in the P710U
# parameter table, so they are intentionally exposed read-only.
P710U_PARAMETERS: tuple[P710UParameterDefinition, ...] = (
    P710UParameterDefinition(
        "F1",
        "Deceleration trigger distance",
        ("75%", "80%", "85%", "90%", "95%"),
    ),
    P710UParameterDefinition(
        "F2",
        "Full-open remote button",
        ("Disabled", "Button A", "Button B", "Button C", "Button D"),
    ),
    P710UParameterDefinition(
        "F3",
        "Integrated-light remote button",
        ("Disabled", "Button A", "Button B", "Button C", "Button D"),
    ),
    P710UParameterDefinition(
        "F4",
        "External-control remote button",
        ("Disabled", "Button A", "Button B", "Button C", "Button D"),
    ),
    P710UParameterDefinition(
        "F5",
        "Photocell activation",
        ("Disabled", "Enabled", "Enabled on closing only"),
    ),
    P710UParameterDefinition(
        "F6",
        "Buzzer alarm",
        ("Disabled", "Enabled"),
    ),
    P710UParameterDefinition(
        "F7",
        "Automatic closing",
        (
            "Disabled",
            "30 seconds",
            "60 seconds",
            "90 seconds",
            "120 seconds",
            "150 seconds",
            "180 seconds",
            "210 seconds",
            "240 seconds",
        ),
    ),
    P710UParameterDefinition(
        "F8",
        "Integrated light duration",
        ("Disabled", "1 minute", "2 minutes", "3 minutes"),
    ),
    P710UParameterDefinition(
        "F9",
        "Overcurrent reaction",
        (
            "Stop",
            "Opening: stop / Closing: reverse 10 cm",
            "Full reverse",
        ),
    ),
    P710UParameterDefinition(
        "A",
        "Overcurrent adjustment",
        (
            "+0.2 A",
            "+0.4 A",
            "+0.6 A",
            "+0.8 A",
            "+1.0 A",
            "+1.2 A",
            "+1.4 A",
            "+1.6 A",
            "+1.8 A",
        ),
    ),
    P710UParameterDefinition("B", "Function B (undocumented)", (), writable=False),
    P710UParameterDefinition(
        "C",
        "Opening current limit",
        ("2 A", "3 A", "4 A", "5 A", "6 A", "7 A", "8 A"),
    ),
    P710UParameterDefinition("D", "Function D (undocumented)", (), writable=False),
    P710UParameterDefinition(
        "E",
        "Closing current limit",
        ("2 A", "3 A", "4 A", "5 A", "6 A", "7 A", "8 A"),
    ),
    P710UParameterDefinition(
        "F",
        "+24 V terminal power",
        ("Continuous power", "Standby mode"),
    ),
)


_RP_RE = re.compile(r"(?:^|\b)ACK RP,1:([^;\r\n]+)")


def parse_parameter_response(payload: str) -> tuple[int, ...] | None:
    """Parse a known ACK RP,1 response."""
    match = _RP_RE.search(payload)
    if not match:
        return None
    try:
        values = tuple(int(item.strip()) for item in match.group(1).split(","))
    except ValueError:
        return None

    if len(values) == len(PARAMETERS):
        return values if validate_parameter_values(values) else None

    if len(values) == len(P710U_PARAMETERS) and all(0 <= value <= 255 for value in values):
        return values

    return None


def validate_parameter_values(values: tuple[int, ...]) -> bool:
    """Validate the exact PS21053/PS21053C profile."""
    return len(values) == len(PARAMETERS) and all(
        0 <= value < len(definition.options)
        for definition, value in zip(PARAMETERS, values, strict=True)
    )


def validate_p710u_write(index: int, value: int) -> bool:
    """Validate one user-requested P710U value without altering reserved fields."""
    if not 0 <= index < len(P710U_PARAMETERS):
        return False
    definition = P710U_PARAMETERS[index]
    return definition.writable and 0 <= value < len(definition.options)


def encode_parameter_write(values: tuple[int, ...]) -> str:
    """Build the PS21053/PS21053C full parameter write command."""
    if not validate_parameter_values(values):
        raise ValueError("Invalid PS21053 parameter set")
    return "WP,1:" + ",".join(str(value) for value in values)


def encode_p710u_parameter_write(values: tuple[int, ...]) -> str:
    """Build the P710U full 15-value WP,1 command.

    Unknown B/D values are preserved verbatim from the preceding RP,1 read.
    """
    if len(values) != len(P710U_PARAMETERS) or not all(0 <= value <= 255 for value in values):
        raise ValueError("Invalid P710U parameter set")
    return "WP,1:" + ",".join(str(value) for value in values)
