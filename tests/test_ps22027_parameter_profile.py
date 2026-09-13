"""Regression tests for the PS22027 verified 20-value parameter profile."""

from __future__ import annotations

import asyncio

from custom_components.tmt_chow.const import ATTR_DEV_PARAM
from custom_components.tmt_chow.hub import TmtCommandError
from custom_components.tmt_chow.ps21050d_hub import TmtChowHub
from custom_components.tmt_chow.ps22027_parameters import (
    APP_PARAMETERS,
    PARAMETER_COUNT,
    decoded_parameter_values,
    encode_parameter_write,
    option_to_wire_value,
    parameter_options_for,
    parse_parameter_response,
    wire_value_to_option,
)


_LIVE_WIRE_VALUES = (
    2,
    20,
    10,
    3,
    2,
    1,
    1,
    1,
    0,
    0,
    1,
    0,
    1,
    0,
    0,
    0,
    1,
    1,
    0,
    0,
)
_LIVE_BODY = ",".join(map(str, _LIVE_WIRE_VALUES))
_EXPECTED_DISPLAY_VALUES = (
    "Hall Sensor",
    "2.0 A",
    "1.0 A",
    "100 %",
    "75 %",
    "50 %",
    "2 sec",
    "2 sec",
    "Function OFF",
    "Mode 1",
    "Function ON",
    "Function OFF",
    "Function ON",
    "Function OFF",
    "Function OFF",
    "Standard Gate Opening",
    "When Terminal Block is at Bottom",
    "Dual Gate",
    "Function OFF",
    "Function OFF",
)


def _hub() -> TmtChowHub:
    return TmtChowHub(
        uuid="test-uuid",
        thing_name="test-thing",
        name="PS22027 test gate",
        endpoint="example.invalid",
        certificate_pem="",
        private_key="",
        source_tag="P9999999",
        product_type="104",
        device_type="PS22027",
    )


def test_ps22027_uses_20_value_verified_schema() -> None:
    hub = _hub()

    assert hub.controller_type == "PS22027"
    assert hub.parameter_model_type == "PS22027"
    assert hub.parameter_model_source == "ps22027_wire20_verified"
    assert hub.model_parameter_schema == APP_PARAMETERS
    assert len(APP_PARAMETERS) == PARAMETER_COUNT == 20
    assert tuple(spec[1] for spec in APP_PARAMETERS[:3]) == (
        "func_slide_gate_operation_mode",
        "func_open_over_current",
        "func_close_over_current",
    )
    assert hub.may_probe_parameters is True
    assert hub.parameter_write_schema_verified is True
    assert hub.supports_parameters is True


def test_ps22027_parser_accepts_exact_20_value_frame_only() -> None:
    hub = _hub()

    assert parse_parameter_response(f"ACK RP,1:{_LIVE_BODY}") == _LIVE_WIRE_VALUES
    assert parse_parameter_response(f"ACK RP:{_LIVE_BODY}") == _LIVE_WIRE_VALUES
    assert parse_parameter_response(_LIVE_BODY) == _LIVE_WIRE_VALUES
    assert parse_parameter_response("ACK RP,1:2,20,10") is None
    assert parse_parameter_response(f"NAK RP,1:{_LIVE_BODY}") is None

    assert hub._decode_parameter_response(f"ACK RP,1:{_LIVE_BODY}") == _LIVE_WIRE_VALUES


def test_ps22027_hall_mode_uses_p190_hall_current_mapping() -> None:
    assert parameter_options_for(1, _LIVE_WIRE_VALUES)[0] == "0.5 A"
    assert parameter_options_for(1, _LIVE_WIRE_VALUES)[-1] == "4.0 A"
    assert wire_value_to_option(0, 2, _LIVE_WIRE_VALUES) == "Hall Sensor"
    assert wire_value_to_option(1, 20, _LIVE_WIRE_VALUES) == "2.0 A"
    assert wire_value_to_option(2, 10, _LIVE_WIRE_VALUES) == "1.0 A"
    assert option_to_wire_value(1, "2.1 A", _LIVE_WIRE_VALUES) == 21
    assert option_to_wire_value(2, "1.5 A", _LIVE_WIRE_VALUES) == 15


def test_ps22027_live_frame_decodes_to_expected_vendor_labels() -> None:
    decoded = decoded_parameter_values(_LIVE_WIRE_VALUES)
    assert decoded is not None
    assert tuple(item["display"] for item in decoded) == _EXPECTED_DISPLAY_VALUES

    assert decoded[1]["mapping_source"] == "p190_hall_current"
    assert decoded[1]["mapping_option_key"] == "option_over_current_setting_p190_hall"
    assert decoded[1]["mapping_offset"] == 5
    assert decoded[2]["mapping_source"] == "p190_hall_current"
    assert decoded[3]["mapping_source"] == "ps22027_app"


def test_ps22027_refresh_uses_rp1_and_keeps_raw_wire_values() -> None:
    hub = _hub()
    calls: list[tuple[str, str]] = []

    async def fake_exchange(payload: str, expected: str) -> str:
        calls.append((payload, expected))
        return f"ACK RP,1:{_LIVE_BODY}"

    hub._async_exchange = fake_exchange  # type: ignore[method-assign]
    asyncio.run(hub.async_refresh_parameters())

    assert calls == [("c=RP,1", "ACK RP,1")]
    assert hub.parameters == _LIVE_WIRE_VALUES
    assert hub.attributes[ATTR_DEV_PARAM] == _LIVE_BODY


def test_ps22027_write_reads_first_writes_once_and_verifies_full_frame() -> None:
    hub = _hub()
    target = option_to_wire_value(1, "2.1 A", _LIVE_WIRE_VALUES)
    updated = list(_LIVE_WIRE_VALUES)
    updated[1] = target
    updated_values = tuple(updated)
    updated_body = ",".join(map(str, updated_values))
    calls: list[tuple[str, str]] = []
    read_count = 0

    async def fake_exchange(payload: str, expected: str) -> str:
        nonlocal read_count
        calls.append((payload, expected))
        if payload == "c=RP,1":
            read_count += 1
            body = _LIVE_BODY if read_count == 1 else updated_body
            return f"ACK RP,1:{body}"
        assert payload == f"c={encode_parameter_write(updated_values)};src=P9999999"
        assert expected == "ACK WP"
        return "ACK WP"

    hub._async_exchange = fake_exchange  # type: ignore[method-assign]
    asyncio.run(hub.async_set_parameter(1, target))

    assert calls == [
        ("c=RP,1", "ACK RP,1"),
        (f"c={encode_parameter_write(updated_values)};src=P9999999", "ACK WP"),
        ("c=RP,1", "ACK RP,1"),
    ]
    assert hub.parameters == updated_values
    assert hub.attributes[ATTR_DEV_PARAM] == updated_body


def test_ps22027_write_rejects_collateral_frame_change() -> None:
    hub = _hub()
    target = option_to_wire_value(1, "2.1 A", _LIVE_WIRE_VALUES)
    requested = list(_LIVE_WIRE_VALUES)
    requested[1] = target
    requested_values = tuple(requested)
    collateral = list(requested_values)
    collateral[14] = 1
    collateral_body = ",".join(map(str, collateral))
    read_count = 0

    async def fake_exchange(payload: str, expected: str) -> str:
        nonlocal read_count
        if payload == "c=RP,1":
            read_count += 1
            body = _LIVE_BODY if read_count == 1 else collateral_body
            return f"ACK RP,1:{body}"
        assert payload == f"c={encode_parameter_write(requested_values)};src=P9999999"
        assert expected == "ACK WP"
        return "ACK WP"

    hub._async_exchange = fake_exchange  # type: ignore[method-assign]

    try:
        asyncio.run(hub.async_set_parameter(1, target))
    except TmtCommandError as err:
        assert err.translation_key == "parameter_verification_failed"
    else:
        raise AssertionError("Unexpected PS22027 collateral change was accepted")

    assert hub.parameters is None


def test_ps22027_mode_change_is_rejected_if_full_frame_becomes_invalid() -> None:
    hub = _hub()
    calls: list[tuple[str, str]] = []

    async def fake_exchange(payload: str, expected: str) -> str:
        calls.append((payload, expected))
        return f"ACK RP,1:{_LIVE_BODY}"

    hub._async_exchange = fake_exchange  # type: ignore[method-assign]

    try:
        asyncio.run(hub.async_set_parameter(0, 1))
    except TmtCommandError as err:
        assert err.translation_key == "unsupported_parameter_value"
    else:
        raise AssertionError("Unsafe PS22027 mode change unexpectedly produced a write")

    assert calls == [("c=RP,1", "ACK RP,1")]
