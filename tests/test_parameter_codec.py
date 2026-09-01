"""Tests for the APK-derived multi-model parameter wire codecs."""

from custom_components.tmt_chow.model_parameter_schemas import M, parameter_schema_for
from custom_components.tmt_chow.model_protocol_profiles import (
    MODEL_PROTOCOL_PROFILES,
    protocol_profile_for,
)
from custom_components.tmt_chow.parameter_codec import (
    decode_model_parameter_response,
    encode_model_parameter_write,
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


def test_every_gate_model_has_schema_and_protocol_profile() -> None:
    assert len(M) == 217
    assert len(MODEL_PROTOCOL_PROFILES) == 217
    assert set(M) == set(MODEL_PROTOCOL_PROFILES)


def test_default_vectors_round_trip_for_every_model() -> None:
    for model in sorted(M):
        defaults = parameter_defaults(model)
        assert defaults is not None, model
        command = encode_model_parameter_write(model, defaults)
        response = _read_response_from_write(model, command)
        decoded = decode_model_parameter_response(model, response)
        assert decoded == defaults, model


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
