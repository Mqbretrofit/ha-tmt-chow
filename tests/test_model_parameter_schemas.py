"""Tests for the APK-derived per-model parameter matrix."""

from custom_components.tmt_chow.model_parameter_schemas import (
    M,
    parameter_name,
    parameter_options,
    parameter_schema_for,
)


def test_all_concrete_gate_models_have_parameter_schema() -> None:
    assert len(M) == 217
    assert all(parameter_schema_for(model) for model in M)


def test_ps21053_schema_matches_verified_layout() -> None:
    schema = parameter_schema_for("PS21053")
    assert schema is not None
    assert len(schema) == 17
    assert parameter_name(schema[0]) == "Operation Direction"
    assert parameter_options(schema[0]) == ("Default", "Reverse")
    assert parameter_name(schema[1]) == "Auto-closing"
    assert parameter_options(schema[1]) == (
        "Function OFF",
        "5 secs",
        "15 secs",
        "30 secs",
        "45 secs",
        "60 secs",
        "80 secs",
        "120 secs",
        "180 secs",
    )


def test_ps21053c_uses_ps21053_schema() -> None:
    assert parameter_schema_for("PS21053C") == parameter_schema_for("PS21053")


def test_unknown_api_only_model_is_not_guessed() -> None:
    # PS25007 has been observed in the API, but neither inspected Android app
    # contains a concrete PS25007 product class from which a schema can be
    # extracted. Do not borrow another model's parameter layout.
    assert parameter_schema_for("PS25007") is None
