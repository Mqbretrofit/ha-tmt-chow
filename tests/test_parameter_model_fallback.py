"""Regression tests for safe model-variant parameter probing."""

from __future__ import annotations

import asyncio

from custom_components.tmt_chow.hub import TmtChowHub, TmtCommandError
from custom_components.tmt_chow.parameter_codec import (
    encode_model_parameter_write,
    parameter_defaults,
)


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


def test_unknown_live_variant_uses_configured_model_for_reads_only() -> None:
    hub = _hub("PS21050")

    hub._set_controller_type("PS21050D")

    assert hub.controller_type == "PS21050D"
    assert hub.configured_controller_type == "PS21050"
    assert hub.parameter_model_type == "PS21050"
    assert hub.parameter_model_source == "configured_fallback"
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


def test_fallback_variant_parameter_write_is_blocked_before_exchange() -> None:
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
        raise AssertionError("Fallback parameter write was not rejected")

    assert calls == 0


def test_fallback_variant_refresh_uses_configured_read_profile() -> None:
    hub = _hub("PS21050")
    hub._set_controller_type("PS21050D")
    defaults = parameter_defaults("PS21050")
    assert defaults is not None
    encoded = encode_model_parameter_write("PS21050", defaults)
    assert encoded.startswith("WP,1:")
    response = "ACK RP,1:" + encoded.removeprefix("WP,1:")
    calls: list[tuple[str, str]] = []

    async def fake_exchange(payload: str, expected: str) -> str:
        calls.append((payload, expected))
        return response

    hub._async_exchange = fake_exchange  # type: ignore[method-assign]

    asyncio.run(hub.async_refresh_parameters())

    assert calls == [("c=RP,1", "ACK RP,1")]
    assert hub.parameters == defaults
