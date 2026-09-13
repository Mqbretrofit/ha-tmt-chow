"""Regression coverage for PS20040D alias and pedestrian safety strategy."""

from __future__ import annotations

import asyncio

from custom_components.tmt_chow.controller_types import CAPABILITY_PEDESTRIAN
from custom_components.tmt_chow.hub import TmtCommandError
from custom_components.tmt_chow.pedestrian import (
    PEDESTRIAN_STRATEGY_NONE,
    PEDESTRIAN_STRATEGY_PED_OPEN,
    direct_ped_open_blocked,
    pedestrian_strategy_for,
)
from custom_components.tmt_chow.protocol import decode_dev_status
from custom_components.tmt_chow.ps21050d_hub import TmtChowHub


def _hub(device_type: str = "PS20040") -> TmtChowHub:
    return TmtChowHub(
        uuid="test-uuid",
        thing_name="test-thing",
        name="Test gate",
        endpoint="example.invalid",
        certificate_pem="",
        private_key="",
        source_tag="P9999999",
        product_type="112",
        device_type=device_type,
    )


def test_ps20040d_live_alias_keeps_ps20040_family_pedestrian_and_write_codec() -> None:
    hub = _hub()

    # Account/configured model is PS20040; live DEV INFO later reports PS20040D.
    hub._set_controller_type("PS20040D")

    assert hub.configured_controller_type == "PS20040"
    assert hub.controller_type == "PS20040D"
    assert hub.controller_family == "sliding"
    assert CAPABILITY_PEDESTRIAN in hub.controller_capabilities
    assert hub.pedestrian_strategy == PEDESTRIAN_STRATEGY_PED_OPEN

    # The exact app/live alias uses the PS20040 RP,1/WP,1 schema and keeps the
    # base hub's read-before-write plus mandatory read-back verification.
    assert hub.parameter_model_type == "PS20040"
    assert hub.parameter_model_source == "apk_ps20040_alias"
    assert hub.parameter_schema_verified is True
    assert hub.parameter_write_schema_verified is True
    assert hub.supports_parameters is True


def test_ps25007a_direct_ped_open_is_hard_blocked_before_mqtt() -> None:
    hub = _hub("PS25007A")

    # Even if a future capability import accidentally marks PS25007A as
    # pedestrian-capable, the real-hardware safety deny-list wins.
    hub.controller_capabilities = frozenset({CAPABILITY_PEDESTRIAN})
    assert direct_ped_open_blocked(hub.controller_type) is True
    assert pedestrian_strategy_for(
        hub.controller_type,
        hub.controller_capabilities,
    ) == PEDESTRIAN_STRATEGY_NONE
    assert hub.pedestrian_strategy == PEDESTRIAN_STRATEGY_NONE

    calls: list[tuple[str, str]] = []

    async def fake_exchange(payload: str, expected: str) -> str:
        calls.append((payload, expected))
        raise AssertionError("Unsafe PS25007A pedestrian command reached MQTT")

    hub._async_exchange = fake_exchange  # type: ignore[method-assign]

    try:
        asyncio.run(hub.async_pedestrian_open())
    except TmtCommandError as err:
        assert err.translation_key == "unsupported_controller"
    else:
        raise AssertionError("PS25007A direct pedestrian command was not blocked")

    assert calls == []


def test_ff_battery_status_is_not_exposed_as_127_percent() -> None:
    status = decode_dev_status("00,FF,A0,00,40,00,80,C0,00")

    assert status.position == 0
    assert status.battery_percent is None


def test_valid_battery_percentage_is_preserved() -> None:
    status = decode_dev_status("00,64,A0,00")

    assert status.battery_percent == 100
