"""Safety regression tests for the limited verified PS20005 OURANOS/V2 route."""

from __future__ import annotations

import asyncio

import pytest

from custom_components.tmt_chow.hub import TmtCommandError
from custom_components.tmt_chow.pedestrian import PEDESTRIAN_STRATEGY_NONE
from custom_components.tmt_chow.ps21050d_hub import TmtChowHub


def _hub() -> TmtChowHub:
    return TmtChowHub(
        uuid="12345678901234567890",
        thing_name="test-thing",
        name="PS20005",
        endpoint="example.invalid",
        certificate_pem="",
        private_key="",
        source_tag="P9999999",
        product_type="108",
        device_type="PS20005",
    )


def test_ps20005_mqtt_profile_is_unchanged_without_native_session() -> None:
    hub = _hub()
    assert hub.controller_type == "PS20005"
    assert hub.gate_control_enabled is True
    assert hub.stop_control_enabled is True
    assert hub.parameter_schema_verified is True


def test_ps20005_native_exposes_open_close_but_blocks_untested_actions() -> None:
    hub = _hub()
    hub.set_ouranos_native_session(object())  # type: ignore[arg-type]
    assert hub.gate_control_enabled is True
    assert hub.stop_control_enabled is False
    assert hub.pedestrian_strategy == PEDESTRIAN_STRATEGY_NONE
    assert hub.parameter_schema_verified is True  # RP,1 read remains allowed
    assert hub.parameter_write_schema_verified is False
    assert hub.supports_parameters is False

    with pytest.raises(TmtCommandError, match="STOP"):
        asyncio.run(hub.async_stop_gate())
    with pytest.raises(TmtCommandError, match="parameter writing"):
        asyncio.run(hub.async_set_parameter(0, 1))
    with pytest.raises(TmtCommandError, match="No verified safe pedestrian"):
        asyncio.run(hub.async_pedestrian_open())


def test_ps20005_native_disables_stop_cover_feature_only() -> None:
    from homeassistant.components.cover import CoverEntityFeature
    from custom_components.tmt_chow.cover import TmtChowCover

    hub = _hub()
    cover = TmtChowCover(hub)
    assert cover.supported_features & CoverEntityFeature.STOP

    hub.set_ouranos_native_session(object())  # type: ignore[arg-type]
    features = cover.supported_features
    assert features & CoverEntityFeature.OPEN
    assert features & CoverEntityFeature.CLOSE
    assert not features & CoverEntityFeature.STOP
