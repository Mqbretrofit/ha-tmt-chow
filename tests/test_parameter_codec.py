"""Tests for the APK-derived multi-model parameter wire codecs."""

from custom_components.tmt_chow.model_parameter_schemas import (
    M,
    parameter_options,
    parameter_schema_for,
)
from custom_components.tmt_chow.model_protocol_profiles import (
    MODEL_PROTOCOL_PROFILES,
    protocol_profile_for,
)
from custom_components.tmt_chow.parameter_codec import (
    decode_model_parameter_response,
    encode_model_parameter_write,
    is_editable_parameter,
    parameter_defaults,
)


def _read_response_from_write(model: str, command: str) -> str:
    profile = protocol_profile_for(model)
    assert profile is not None
    uart = profile[0]
    if uart == 0:
        assert command.startswith("WRITE FUNCTION")
        return "ACK READ FUNCTION" + command[len("WRITE FUNCTION") :]
    assert command.startswith("WP,1:")
    return "ACK RP,1:" + command[len("WP,1:") :]


def _valid_logical_vector(model: str) -> tuple[int, ...]:
    """Build a validator-safe logical vector from APK metadata.

    Some vendor classes store defaults in wire units while also carrying an
    offset, and a few defaults are outside the user-selectable option table.
    The round-trip test is about codec reversibility, so use the APK default
    when it is a valid logical value and otherwise choose the first valid
    logical option / numeric value rather than asserting that every APK default
    itself is user-writable.
    """
    schema = parameter_schema_for(model)
    assert schema is not None
    values: list[int] = []
    for spec in schema:
        default = int(spec[5] or 0)
        offset = int(spec[6] or 0)
        logical = default - offset

        if not is_editable_parameter(spec):
            values.append(default)
            continue

        options = parameter_options(spec)
        if options:
            if 0 <= logical < len(options):
                values.append(logical)
            elif 0 <= default < len(options):
                values.append(default)
            else:
                values.append(0)
            continue

        minimum = int(spec[11]) if spec[11] is not None else None
        maximum = int(spec[12]) if spec[12] is not None else None
        value = logical
        if minimum is not None and value < minimum:
            value = minimum
        if maximum is not None and value > maximum:
            value = maximum
        increment = int(spec[13] or 0)
        if increment > 0:
            origin = minimum or 0
            value = origin + round((value - origin) / increment) * increment
            if minimum is not None:
                value = max(value, minimum)
            if maximum is not None:
                value = min(value, maximum)
        values.append(value)
    return tuple(values)


def test_every_gate_model_has_schema_and_protocol_profile() -> None:
    assert len(M) == 217
    assert len(MODEL_PROTOCOL_PROFILES) == 217
    assert set(M) == set(MODEL_PROTOCOL_PROFILES)


def test_validator_safe_vectors_round_trip_for_every_model() -> None:
    for model in sorted(M):
        values = _valid_logical_vector(model)
        command = encode_model_parameter_write(model, values)
        response = _read_response_from_write(model, command)
        decoded = decode_model_parameter_response(model, response)
        assert decoded == values, model


def test_parameter_defaults_stays_available_as_apk_metadata() -> None:
    defaults = parameter_defaults("PS21053")
    assert defaults is not None
    assert len(defaults) == 17


def test_ps21053_write_format_stays_backward_compatible() -> None:
    values = (1, 3, 0, 3, 3, 3, 11, 1, 0, 1, 0, 2, 3, 1, 0, 0, 0)
    assert encode_model_parameter_write("PS21053", values) == (
        "WP,1:1,3,0,3,3,3,11,1,0,1,0,2,3,1,0,0,0"
    )


def test_ps21053_real_response_decodes_to_17_values() -> None:
    payload = "ACK RP,1:1,3,0,3,3,3,11,1,0,1,0,2,3,1,0,0,0"
    decoded = decode_model_parameter_response("PS21053", payload)
    assert decoded == (1, 3, 0, 3, 3, 3, 11, 1, 0, 1, 0, 2, 3, 1, 0, 0, 0)
    assert len(parameter_schema_for("PS21053") or ()) == 17


def test_ps21053c_uses_ps21053_protocol() -> None:
    defaults = parameter_defaults("PS21053C")
    assert defaults == parameter_defaults("PS21053")
    command = encode_model_parameter_write("PS21053C", defaults)
    decoded = decode_model_parameter_response(
        "PS21053C",
        _read_response_from_write("PS21053C", command),
    )
    assert decoded == defaults


def test_unknown_api_only_model_is_never_guessed() -> None:
    assert parameter_schema_for("PS25007") is None
    assert protocol_profile_for("PS25007") is None
