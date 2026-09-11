"""Regression tests for the PS22027 20-value read-only parameter profile."""

from __future__ import annotations

import asyncio

from custom_components.tmt_chow.const import ATTR_DEV_PARAM
from custom_components.tmt_chow.hub import TmtCommandError
from custom_components.tmt_chow.ps21050d_hub import TmtChowHub


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


def test_ps22027_uses_20_value_read_only_schema() -> None:
    hub = _hub()

    assert hub.controller_type == "PS22027"
    assert hub.parameter_model_type == "PS22027"
    assert hub.parameter_model_source == "ps22027_wire20_read_only"
    assert hub.model_parameter_schema is not None
    assert len(hub.model_parameter_schema) == 20
    assert tuple(spec[1] for spec in hub.model_parameter_schema[:3]) == (
        "func_slide_gate_operation_mode",
        "func_open_over_current",
        "func_close_over_current",
    )
    assert hub.may_probe_parameters is True
    assert hub.parameter_write_schema_verified is False
    assert hub.supports_parameters is False


def test_ps22027_parser_accepts_exact_20_value_frame_only() -> None:
    hub = _hub()

    assert hub._decode_parameter_response(f"ACK RP,1:{_LIVE_BODY}") == _LIVE_WIRE_VALUES
    assert hub._decode_parameter_response(f"ACK RP:{_LIVE_BODY}") == _LIVE_WIRE_VALUES
    assert hub._decode_parameter_response(_LIVE_BODY) == _LIVE_WIRE_VALUES
    assert hub._decode_parameter_response("ACK RP,1:2,20,10") is None
    assert hub._decode_parameter_response(f"NAK RP,1:{_LIVE_BODY}") is None


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


def test_ps22027_parameter_writes_remain_blocked() -> None:
    hub = _hub()

    try:
        asyncio.run(hub.async_set_parameter(0, 0))
    except TmtCommandError as err:
        assert err.translation_key == "unsupported_controller"
    else:
        raise AssertionError("PS22027 test profile unexpectedly allowed a parameter write")
