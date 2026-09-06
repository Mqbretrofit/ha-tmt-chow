"""Regression tests for the live PS21050D -> vendor PS21050 app alias."""

from __future__ import annotations

import asyncio

from custom_components.tmt_chow.model_parameter_schemas import parameter_options
from custom_components.tmt_chow.parameter_codec import (
    decode_model_parameter_response,
    encode_model_parameter_write,
)
from custom_components.tmt_chow.ps21050d_hub import TmtChowHub

_LIVE_WIRE_VALUES = (
    0,
    1,
    1,
    2,
    2,
    1,
    3,
    1,
    2,
    0,
    0,
    1,
    0,
    1,
    0,
    1,
    0,
    1,
    1,
    0,
)
_LIVE_BODY = ",".join(map(str, _LIVE_WIRE_VALUES))
_APK_WIRE_KEYS = (
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
_APK_OPTION_COUNTS = (3, 4, 4, 4, 4, 4, 5, 10, 10, 9, 7, 2, 2, 2, 2, 2, 2, 2, 2, 7)


def _hub(device_type: str) -> TmtChowHub:
    return TmtChowHub(
        uuid="test-uuid",
        thing_name="test-thing",
        name="Test gate",
        endpoint="example.invalid",
        certificate_pem="",
        private_key="",
        source_tag="P9999999",
        product_type="108",
        device_type=device_type,
    )


def _wire_specs(schema: tuple) -> tuple:
    """Return schema entries that consume RP,1/WP,1 wire positions."""
    return tuple(spec for spec in schema if int(spec[3] or 0) < 10)


def test_ps21050d_uses_vendor_ps21050_profile() -> None:
    hub = _hub("PS21050")

    hub._set_controller_type("PS21050D")

    assert hub.controller_type == "PS21050D"
    assert hub.configured_controller_type == "PS21050"
    assert hub.controller_family == "swing"
    assert "pedestrian" in hub.controller_capabilities
    assert hub.parameter_model_type == "PS21050"
    assert hub.parameter_model_source == "apk_ps21050_alias"
    assert hub.model_parameter_schema is not None
    wire_specs = _wire_specs(hub.model_parameter_schema)
    assert len(wire_specs) == 20
    assert tuple(spec[1] for spec in wire_specs) == _APK_WIRE_KEYS
    assert hub.may_probe_parameters is True
    assert hub.parameter_write_schema_verified is True
    assert hub.supports_parameters is True


def test_ps21050_apk_option_counts_match_extracted_wire_model() -> None:
    hub = _hub("PS21050")
    hub._set_controller_type("PS21050D")
    schema = hub.model_parameter_schema
    assert schema is not None

    wire_specs = _wire_specs(schema)
    option_counts = tuple(len(parameter_options(spec)) for spec in wire_specs)
    assert option_counts == _APK_OPTION_COUNTS
    assert all(
        0 <= value < count
        for value, count in zip(_LIVE_WIRE_VALUES, option_counts, strict=True)
    )


def test_exact_live_model_keeps_normal_verified_support() -> None:
    hub = _hub("PS21053C")

    hub._set_controller_type("PS21053C")

    assert hub.parameter_model_type == "PS21053C"
    assert hub.parameter_model_source == "controller"
    assert hub.may_probe_parameters is True
    assert hub.parameter_write_schema_verified is True
    assert hub.supports_parameters is True


def test_ps21050d_refresh_uses_vendor_rp1_decoder() -> None:
    hub = _hub("PS21050")
    hub._set_controller_type("PS21050D")
    calls: list[tuple[str, str]] = []

    expected_logical = decode_model_parameter_response(
        "PS21050", f"ACK RP,1:{_LIVE_BODY}"
    )
    assert expected_logical is not None

    async def fake_exchange(payload: str, expected: str) -> str:
        calls.append((payload, expected))
        return f"ACK RP,1:{_LIVE_BODY}"

    hub._async_exchange = fake_exchange  # type: ignore[method-assign]

    asyncio.run(hub.async_refresh_parameters())

    assert calls == [("c=RP,1", "ACK RP,1")]
    assert hub.parameters == expected_logical


def test_ps21050d_write_uses_vendor_wp1_and_verifies_readback() -> None:
    hub = _hub("PS21050")
    hub._set_controller_type("PS21050D")
    schema = hub.model_parameter_schema
    assert schema is not None

    current_logical = decode_model_parameter_response(
        "PS21050", f"ACK RP,1:{_LIVE_BODY}"
    )
    assert current_logical is not None

    first_wire_index = next(
        index for index, spec in enumerate(schema) if int(spec[3] or 0) < 10
    )
    updated_logical = list(current_logical)
    updated_logical[first_wire_index] = 1
    updated_logical_values = tuple(updated_logical)

    updated_wire_values = list(_LIVE_WIRE_VALUES)
    updated_wire_values[0] = 1
    updated_body = ",".join(map(str, updated_wire_values))

    expected_command = encode_model_parameter_write(
        "PS21050", updated_logical_values
    )
    assert expected_command == f"WP,1:{updated_body}"

    calls: list[tuple[str, str]] = []

    async def fake_exchange(payload: str, expected: str) -> str:
        calls.append((payload, expected))
        if len(calls) == 1:
            return f"ACK RP,1:{_LIVE_BODY}"
        if len(calls) == 2:
            assert payload == f"c={expected_command};src=P9999999"
            assert expected == "ACK WP"
            return "ACK WP"
        return f"ACK RP,1:{updated_body}"

    hub._async_exchange = fake_exchange  # type: ignore[method-assign]

    asyncio.run(hub.async_set_parameter(first_wire_index, 1))

    assert calls == [
        ("c=RP,1", "ACK RP,1"),
        (f"c={expected_command};src=P9999999", "ACK WP"),
        ("c=RP,1", "ACK RP,1"),
    ]
    assert hub.parameters == decode_model_parameter_response(
        "PS21050", f"ACK RP,1:{updated_body}"
    )


def test_ps21050d_alias_is_not_used_for_unrelated_configured_model() -> None:
    hub = _hub("PS21051")
    hub._set_controller_type("PS21050D")

    assert hub.controller_type == "PS21050D"
    assert hub.parameter_model_type != "PS21050"
    assert hub.parameter_write_schema_verified is False
