"""TMT Chow parameter parsing and PS21053/PS21053C write definitions."""

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
    """Parse a known ACK RP,1 response format.

    PS21053/PS21053C use the verified 17-value parameter profile and are
    validated strictly against the known option definitions.

    PS22087B (P710U / product 118) returns a 15-value RP,1 set. We currently
    accept that profile for read/state synchronization only. Its parameter
    meanings and writable ranges are not yet verified, so writes remain
    disabled elsewhere in the integration.
    """
    match = _RP_RE.search(payload)
    if not match:
        return None
    try:
        values = tuple(int(item.strip()) for item in match.group(1).split(","))
    except ValueError:
        return None

    if len(values) == len(PARAMETERS):
        return values if validate_parameter_values(values) else None

    # Verified from a real PS22087B/P710U response and matching Shadow
    # DEV PARAM payload. Keep this deliberately conservative: read-only,
    # non-negative byte-sized values until the vendor profile is mapped.
    if len(values) == 15 and all(0 <= value <= 255 for value in values):
        return values

    return None


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


# P710U / PS22087B parameter profile verified against the PowerTech PG
# series P710U manual. Function keys B and D are not documented in that
# manual; if a controller reports them they are exposed read-only as raw
# values rather than guessed.
P710U_FUNCTIONS: dict[str, tuple[str, dict[int, str]]] = {
    "1": ("Deceleration trigger distance", {
        1: "75%", 2: "80%", 3: "85%", 4: "90%", 5: "95%",
    }),
    "2": ("Full-open remote button", {
        0: "Disabled", 1: "Button A", 2: "Button B", 3: "Button C", 4: "Button D",
    }),
    "3": ("Integrated-light remote button", {
        0: "Disabled", 1: "Button A", 2: "Button B", 3: "Button C", 4: "Button D",
    }),
    "4": ("External-control remote button", {
        0: "Disabled", 1: "Button A", 2: "Button B", 3: "Button C", 4: "Button D",
    }),
    "5": ("Photocell activation", {
        0: "Disabled", 1: "Enabled", 2: "Enabled on closing only",
    }),
    "6": ("Buzzer alarm", {
        1: "Disabled", 2: "Enabled",
    }),
    "7": ("Automatic closing", {
        1: "Disabled", 2: "30 seconds", 3: "60 seconds", 4: "90 seconds",
        5: "120 seconds", 6: "150 seconds", 7: "180 seconds",
        8: "210 seconds", 9: "240 seconds",
    }),
    "8": ("Integrated light duration", {
        1: "Disabled", 2: "1 minute", 3: "2 minutes", 4: "3 minutes",
    }),
    "9": ("Overcurrent reaction", {
        1: "Stop",
        2: "Opening: stop / Closing: reverse 10 cm",
        3: "Full reverse",
    }),
    "A": ("Overcurrent adjustment", {
        0: "+0.2 A", 1: "+0.4 A", 2: "+0.5 A", 3: "+0.6 A",
        4: "+0.8 A", 5: "+1.0 A", 6: "+1.2 A", 7: "+1.4 A",
        8: "+1.6 A", 9: "+1.8 A",
    }),
    "C": ("Opening current limit", {
        1: "2 A", 2: "3 A", 3: "4 A", 4: "5 A",
        5: "6 A", 6: "7 A", 7: "8 A",
    }),
    "E": ("Closing current limit", {
        1: "2 A", 2: "3 A", 3: "4 A", 4: "5 A",
        5: "6 A", 6: "7 A", 7: "8 A",
    }),
    "F": ("+24 V terminal power", {
        1: "Continuous power", 2: "Standby mode",
    }),
}

_READ_FUNCTION_RE = re.compile(r"(?:^|\\b)ACK READ FUNCTION,([^;\\r\\n]+)")


def parse_read_function_response(payload: str) -> dict[str, int] | None:
    """Parse ACK READ FUNCTION,key:value,... while preserving key order."""
    match = _READ_FUNCTION_RE.search(payload)
    if not match:
        return None
    result: dict[str, int] = {}
    for item in match.group(1).split(","):
        if ":" not in item:
            return None
        key, raw_value = item.split(":", 1)
        key = key.strip().upper()
        try:
            value = int(raw_value.strip(), 10)
        except ValueError:
            return None
        if not key or value < 0 or value > 255:
            return None
        result[key] = value
    return result or None


def encode_write_function(values: dict[str, int]) -> str:
    """Build the full P710U WRITE FUNCTION payload from current values."""
    if not values:
        raise ValueError("Empty P710U function set")
    parts: list[str] = []
    for key, value in values.items():
        if not key or not 0 <= value <= 255:
            raise ValueError("Invalid P710U function value")
        parts.append(f"{key}:{value}")
    return "WRITE FUNCTION," + ",".join(parts)
