"""Regression tests for safe model-variant parameter probing."""

from __future__ import annotations

import asyncio

from custom_components.tmt_chow.hub import TmtChowHub, TmtCommandError
from custom_components.tmt_chow.ps21050d_parameters import (
    PARAMETER_COUNT,
    parse_parameter_response,
)

_LIVE_VALUES = (
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
_LIVE_BODY = ",".join(map(str, _LIVE_VALUES))


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


def test_ps21050d_uses_explicit_live_raw_read_only_profile() -> None:
    hub = _hub("PS21050")

    hub._set_controller_type("PS21050D")

    assert hub.controller_type == "PS21050D"
    assert hub.configured_controller_type == "PS21050"
    assert hub.parameter_model_type == "PS21050D"
    assert hub.parameter_model_source == "live_raw_read_only"
    assert hub.model_parameter_schema is not None
    assert len(hub.model_parameter_schema) == PARAMETER_COUNT == 20
    assert hub.may_probe_parameters is True
    assert hub.parameter_write_schema_verified is False
    assert hub.supports_parameters is False


def test_exact_live_model_keeps_verified_write_support() -> None:
    hub = _hub("PS21053C")

    hub._set_controller_type("PS21053C")

    assert hub.parameter_model_type == "PS21053C"
    assert hub.parameter_model_source == "controller"
    assert hub.may_probe_parameters is True
    assert hub.parameter_write_schema_verified is True
    assert hub.supports_parameters is True


def test_ps21050d_parameter_write_is_blocked_before_exchange() -> None:
    hub = _hub("PS21050")
    hub._set_controller_type("PS21050D")
    calls = 0

    async def fake_exchange(payload: str, expected: str) -> str:
        nonlocal calls
        calls += 1
        raise AssertionError(f"Unexpected exchange: {payload} / {expected}")

    hub._async_exchange = fake_exchange  # type: ignore[method-assign]

    try:
        asyncio.run(hub.async_set_parameter(0, 0))
    except TmtCommandError as err:
        assert err.translation_key == "unsupported_controller"
    else:
        raise AssertionError("PS21050D parameter write was not rejected")

    assert calls == 0


def test_ps21050d_refresh_uses_rp1_and_captures_live_frame() -> None:
    hub = _hub("PS21050")
    hub._set_controller_type("PS21050D")
    calls: list[tuple[str, str]] = []

    async def fake_exchange(payload: str, expected: str) -> str:
        calls.append((payload, expected))
        return f"ACK RP,1:{_LIVE_BODY}"

    hub._async_exchange = fake_exchange  # type: ignore[method-assign]

    asyncio.run(hub.async_refresh_parameters())

    assert calls == [("c=RP,1", "ACK RP,1")]
    assert hub.parameters == _LIVE_VALUES


def test_ps21050d_parser_accepts_ack_and_shadow_body_only() -> None:
    assert parse_parameter_response(f"ACK RP,1:{_LIVE_BODY}") == _LIVE_VALUES
    assert parse_parameter_response(_LIVE_BODY) == _LIVE_VALUES
    assert parse_parameter_response("ACK RP,1:0,1") is None
    assert parse_parameter_response(f"NAK RP,1:{_LIVE_BODY}") is None
