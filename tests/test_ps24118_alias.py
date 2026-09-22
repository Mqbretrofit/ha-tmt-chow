"""Regression coverage for PS24118 / PS24118C standby-state handling."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import custom_components.tmt_chow.ps21050d_hub as hub_module
from custom_components.tmt_chow.controller_types import (
    CAPABILITY_PEDESTRIAN,
    FAMILY_SWING,
)
from custom_components.tmt_chow.pedestrian import PEDESTRIAN_STRATEGY_PED_OPEN
from custom_components.tmt_chow.ps21050d_hub import TmtChowHub


def _hub() -> TmtChowHub:
    return TmtChowHub(
        uuid="test-uuid",
        thing_name="test-thing",
        name="PS24118 test gate",
        endpoint="example.invalid",
        certificate_pem="",
        private_key="",
        source_tag="P9999999",
        product_type="197",
        device_type="PS24118",
    )


def test_ps24118_reuses_only_p190u_family_and_pedestrian_capability() -> None:
    hub = _hub()

    assert hub.controller_type == "PS24118"
    assert hub.controller_family == FAMILY_SWING
    assert CAPABILITY_PEDESTRIAN in hub.controller_capabilities
    assert hub.pedestrian_strategy == PEDESTRIAN_STRATEGY_PED_OPEN

    # The P190U identity evidence is used only for family/UI capabilities.
    # Parameter schemas and writes remain disabled for this unverified variant.
    assert hub.parameter_model_type is None
    assert hub.parameter_schema_verified is False
    assert hub.parameter_write_schema_verified is False
    assert hub.supports_parameters is False

    hub._set_controller_type("PS24118C")

    assert hub.controller_type == "PS24118C"
    assert hub.controller_family == FAMILY_SWING
    assert CAPABILITY_PEDESTRIAN in hub.controller_capabilities
    assert hub.pedestrian_strategy == PEDESTRIAN_STRATEGY_PED_OPEN
    assert hub.parameter_model_type is None
    assert hub.supports_parameters is False


def test_ps24118_stale_shadow_status_cannot_override_live_state() -> None:
    hub = _hub()
    hub.position = 100
    hub.is_operating = False
    hub.movement = None

    # Real diagnostics show DEV INFO P190U,PS24118C,V02 while the classic
    # Shadow may remain on the pre-standby position. Keep identity metadata,
    # but do not let that stale DEV STATUS overwrite the live RS state.
    hub._apply_reported(
        {
            "dev status": "60,64,AA,00,40,00,00,40,00",
            "dev info": "P190U,PS24118C,V02",
        }
    )

    assert hub.controller_type == "PS24118C"
    assert hub.position == 100
    assert hub.is_operating is False


def test_ps24118_monitor_publishes_read_only_rs_only() -> None:
    hub = _hub()
    published: list[tuple[str, str]] = []

    async def fake_publish(topic: str, payload: str) -> None:
        published.append((topic, payload))

    hub._mqtt.async_publish = fake_publish  # type: ignore[method-assign]

    with patch.object(
        hub_module,
        "_PS24118_STATUS_REFRESH_DELAYS",
        (0.0, 0.0, 0.0),
    ):
        asyncio.run(hub._async_ps24118_status_monitor())

    assert published == [
        (hub.rx_topic, "c=RS;src=P9999999"),
        (hub.rx_topic, "c=RS;src=P9999999"),
        (hub.rx_topic, "c=RS;src=P9999999"),
    ]


def test_ps24118_full_open_is_sent_once_then_status_monitor_starts() -> None:
    hub = _hub()
    commands: list[tuple[str, str, str | None]] = []
    monitor_starts = 0

    async def fake_command(
        command: str,
        acknowledgement: str,
        *,
        motion_direction: str | None = None,
    ) -> bool:
        commands.append((command, acknowledgement, motion_direction))
        return True

    def fake_start_monitor() -> None:
        nonlocal monitor_starts
        monitor_starts += 1

    hub._async_command = fake_command  # type: ignore[method-assign]
    hub._start_ps24118_status_monitor = fake_start_monitor  # type: ignore[method-assign]

    asyncio.run(hub.async_open())

    assert commands == [("FULL OPEN", "ACK FULL OPEN", "opening")]
    assert monitor_starts == 1
