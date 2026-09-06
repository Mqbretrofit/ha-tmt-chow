"""Regression tests for the live PS21050D -> vendor PS21050 app alias."""

from __future__ import annotations

import asyncio

from custom_components.tmt_chow.hub import TmtCommandError
from custom_components.tmt_chow.model_parameter_schemas import parameter_options
from custom_components.tmt_chow.parameter_codec import encode_model_parameter_write
from custom_components.tmt_chow.ps21050d_hub import TmtChowHub

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
_APK_KEYS = (
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
    assert len(hub.model_parameter_schema) == 20
    assert tuple(spec[1] for spec in hub.model_parameter_schema) == _APK_KEYS
    assert hub.may_probe_parameters is True
    assert hub.parameter_write_schema_verified is True
    assert hub.supports_parameters is True


def test_ps21050_apk_options_match_extracted_model() -> None:
    hub = _hub("PS21050")
    hub._set_controller_type("PS21050D")
    schema = hub.model_parameter_schema
    assert schema is not None

    assert parameter_options(schema[0]) == (
        "overcurrent",
        "limit_switch",
        "hall_sensor",
    )
    assert parameter_options(schema[1]) == ("2_a", "3_a", "4_a", "5_a")
    assert parameter_options(schema[3]) == ("40_percent", "50_percent", "75_percent", "100_percent")
    assert parameter_options(schema[11]) == ("function_off", "function_on")


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

    async def fake_exchange(payload: str, expected: str) -> str:
        calls.append((payload, expected))
        return f"ACK RP,1:{_LIVE_BODY}"

    hub._async_exchange = fake_exchange  # type: ignore[method-assign]

    asyncio.run(hub.async_refresh_parameters())

    assert calls == [("c=RP,1", "ACK RP,1")]
    assert hub.parameters == _LIVE_VALUES


def test_ps21050d_write_uses_vendor_ps21050_wp1_and_verifies_readback() -> None:
    hub = _hub("PS21050")
    hub._set_controller_type("PS21050D")

    updated = list(_LIVE_VALUES)
    updated[0] = 1
    updated_values = tuple(updated)
    expected_command = encode_model_parameter_write("PS21050", updated_values)
    assert expected_command == "WP,1:" + ",".join(map(str, updated_values))

    calls: list[tuple[str, str]] = []

    async def fake_exchange(payload: str, expected: str) -> str:
        calls.append((payload, expected))
        if len(calls) == 1:
            return f"ACK RP,1:{_LIVE_BODY}"
        if len(calls) == 2:
            assert payload == f"c={expected_command};src=P9999999"
            assert expected == "ACK WP"
            return "ACK WP"
        return "ACK RP,1:" + ",".join(map(str, updated_values))

    hub._async_exchange = fake_exchange  # type: ignore[method-assign]

    asyncio.run(hub.async_set_parameter(0, 1))

    assert calls == [
        ("c=RP,1", "ACK RP,1"),
        (f"c={expected_command};src=P9999999", "ACK WP"),
        ("c=RP,1", "ACK RP,1"),
    ]
    assert hub.parameters == updated_values


def test_ps21050d_alias_is_not_used_for_unrelated_configured_model() -> None:
    hub = _hub("PS21051")
    hub._set_controller_type("PS21050D")

    assert hub.controller_type == "PS21050D"
    assert hub.parameter_model_type != "PS21050"
    assert hub.parameter_write_schema_verified is False
