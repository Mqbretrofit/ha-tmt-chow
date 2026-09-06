"""Regression tests for the live PS21050D -> vendor PS21050 app alias."""

from __future__ import annotations

import asyncio

from custom_components.tmt_chow.hub import TmtCommandError
from custom_components.tmt_chow.ps21050d_hub import TmtChowHub
from custom_components.tmt_chow.ps21050d_parameters import (
    APP_PARAMETERS,
    PARAMETER_COUNT,
    encode_parameter_write,
    parameter_options_for,
    parse_parameter_response,
    validate_wire_values,
    wire_value_to_option,
)

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


def test_ps21050d_uses_exact_vendor_ps21050_wire_profile() -> None:
    hub = _hub("PS21050")
    hub._set_controller_type("PS21050D")

    assert hub.controller_type == "PS21050D"
    assert hub.configured_controller_type == "PS21050"
    assert hub.controller_family == "swing"
    assert "pedestrian" in hub.controller_capabilities
    assert hub.parameter_model_type == "PS21050D"
    assert hub.parameter_model_source == "apk_ps21050_alias"
    assert hub.model_parameter_schema == APP_PARAMETERS
    assert len(APP_PARAMETERS) == PARAMETER_COUNT == 20
    assert tuple(spec[1] for spec in APP_PARAMETERS) == _APK_WIRE_KEYS
    assert hub.may_probe_parameters is True
    assert hub.parameter_write_schema_verified is True
    assert hub.supports_parameters is True


def test_ps21050d_option_tables_match_apk_and_live_frame() -> None:
    assert tuple(
        len(parameter_options_for(index, _LIVE_WIRE_VALUES))
        for index in range(PARAMETER_COUNT)
    ) == _APK_OPTION_COUNTS
    assert validate_wire_values(_LIVE_WIRE_VALUES) == _LIVE_WIRE_VALUES

    assert wire_value_to_option(0, 0, _LIVE_WIRE_VALUES) == "Overcurrent"
    assert wire_value_to_option(1, 1, _LIVE_WIRE_VALUES) == "3 A"
    assert wire_value_to_option(2, 1, _LIVE_WIRE_VALUES) == "3 A"
    assert wire_value_to_option(3, 2, _LIVE_WIRE_VALUES) == "75 %"
    assert wire_value_to_option(11, 1, _LIVE_WIRE_VALUES) == "Function ON"
    assert wire_value_to_option(18, 1, _LIVE_WIRE_VALUES) == "Dual Gate"


def test_ps21050d_hall_current_table_uses_vendor_offset() -> None:
    hall = list(_LIVE_WIRE_VALUES)
    hall[0] = 2
    hall[1] = 15
    hall[2] = 15
    values = tuple(hall)

    assert validate_wire_values(values) == values
    assert wire_value_to_option(0, 2, values) == "Hall Sensor"
    assert wire_value_to_option(1, 15, values) == "1.5 A"
    assert wire_value_to_option(2, 15, values) == "1.5 A"


def test_ps21050d_parser_accepts_exact_live_frame_only() -> None:
    assert parse_parameter_response(f"ACK RP,1:{_LIVE_BODY}") == _LIVE_WIRE_VALUES
    assert parse_parameter_response(_LIVE_BODY) == _LIVE_WIRE_VALUES
    assert parse_parameter_response("ACK RP,1:0,1") is None
    assert parse_parameter_response(f"NAK RP,1:{_LIVE_BODY}") is None


def test_ps21050d_refresh_uses_rp1_and_keeps_raw_wire_values() -> None:
    hub = _hub("PS21050")
    hub._set_controller_type("PS21050D")
    calls: list[tuple[str, str]] = []

    async def fake_exchange(payload: str, expected: str) -> str:
        calls.append((payload, expected))
        return f"ACK RP,1:{_LIVE_BODY}"

    hub._async_exchange = fake_exchange  # type: ignore[method-assign]
    asyncio.run(hub.async_refresh_parameters())

    assert calls == [("c=RP,1", "ACK RP,1")]
    assert hub.parameters == _LIVE_WIRE_VALUES


def test_ps21050d_write_uses_one_wp1_and_readback_verification() -> None:
    hub = _hub("PS21050")
    hub._set_controller_type("PS21050D")

    updated = list(_LIVE_WIRE_VALUES)
    updated[11] = 0
    updated_values = tuple(updated)
    updated_body = ",".join(map(str, updated_values))
    expected_command = encode_parameter_write(updated_values)
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
    asyncio.run(hub.async_set_parameter(11, 0))

    assert calls == [
        ("c=RP,1", "ACK RP,1"),
        (f"c={expected_command};src=P9999999", "ACK WP"),
        ("c=RP,1", "ACK RP,1"),
    ]
    assert hub.parameters == updated_values


def test_motor_type_transition_is_rejected_if_current_encoding_conflicts() -> None:
    hub = _hub("PS21050")
    hub._set_controller_type("PS21050D")
    calls: list[tuple[str, str]] = []

    async def fake_exchange(payload: str, expected: str) -> str:
        calls.append((payload, expected))
        return f"ACK RP,1:{_LIVE_BODY}"

    hub._async_exchange = fake_exchange  # type: ignore[method-assign]

    try:
        asyncio.run(hub.async_set_parameter(0, 2))
    except TmtCommandError as err:
        assert err.translation_key == "unsupported_parameter_value"
    else:
        raise AssertionError("Unsafe Motor Type transition was not rejected")

    # Only the safe read occurred; no WP,1 was sent.
    assert calls == [("c=RP,1", "ACK RP,1")]


def test_exact_live_model_keeps_normal_verified_support() -> None:
    hub = _hub("PS21053C")
    hub._set_controller_type("PS21053C")

    assert hub.parameter_model_type == "PS21053C"
    assert hub.parameter_model_source == "controller"
    assert hub.parameter_write_schema_verified is True


def test_unrelated_configured_model_keeps_ps21050d_raw_read_only_fallback() -> None:
    hub = _hub("PS21051")
    hub._set_controller_type("PS21050D")

    assert hub.controller_type == "PS21050D"
    assert hub.parameter_model_type == "PS21050D"
    assert hub.parameter_model_source == "live_raw_read_only"
    assert hub.model_parameter_schema is not None
    assert len(hub.model_parameter_schema) == 20
    assert hub.model_parameter_schema[0][1] == "ps21050d_raw_01"
    assert hub.parameter_write_schema_verified is False
    assert hub.supports_parameters is False
