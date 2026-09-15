"""Regression tests for the verified PS25007 -> PS25007A pedestrian path."""

from __future__ import annotations

import asyncio

import pytest

from custom_components.tmt_chow.hub import TmtCommandError
from custom_components.tmt_chow.pedestrian import (
    PEDESTRIAN_STRATEGY_NONE,
    PEDESTRIAN_STRATEGY_PED_OPEN,
)
from custom_components.tmt_chow.ps25007a_hub import TmtChowHub


def _hub(source_tag: str = "P00317D9") -> TmtChowHub:
    hub = TmtChowHub(
        uuid="test-uuid",
        thing_name="test-thing",
        name="Test gate",
        endpoint="example.invalid",
        certificate_pem="",
        private_key="",
        source_tag=source_tag,
        product_type="112",
        device_type="PS25007",
    )
    hub._set_controller_type("PS25007A")
    hub.position = 0
    hub.is_operating = False
    hub.device_online = True
    hub._mqtt._connected.set()
    return hub


def test_ps25007a_pedestrian_requires_identified_source_tag() -> None:
    hub = _hub("P9999999")
    assert hub.pedestrian_strategy == PEDESTRIAN_STRATEGY_NONE

    with pytest.raises(TmtCommandError, match="authenticated-user source tag"):
        asyncio.run(hub.async_pedestrian_open())


def test_ps25007a_identified_source_enables_pedestrian_strategy() -> None:
    hub = _hub()
    assert hub.configured_controller_type == "PS25007"
    assert hub.controller_type == "PS25007A"
    assert hub.pedestrian_strategy == PEDESTRIAN_STRATEGY_PED_OPEN


def test_ps25007a_pedestrian_publishes_exactly_once_without_waiting_for_ack() -> None:
    hub = _hub()
    calls: list[tuple[str, str]] = []

    async def fake_publish(topic: str, payload: str) -> None:
        calls.append((topic, payload))

    hub._mqtt.async_publish = fake_publish  # type: ignore[method-assign]

    asyncio.run(hub.async_pedestrian_open())

    assert calls == [
        (hub.rx_topic, "c=PED OPEN;src=P00317D9"),
    ]
    assert hub._waiters == []


def test_ps25007a_second_parameter_starts_timed_open_state() -> None:
    hub = _hub()
    values = [0] * 17
    values[7] = 1  # Pedestrian Mode = 6 seconds.
    hub.parameters = tuple(values)

    async def fake_publish(topic: str, payload: str) -> None:
        return None

    hub._mqtt.async_publish = fake_publish  # type: ignore[method-assign]

    async def run_test() -> None:
        await hub.async_pedestrian_open()
        assert hub.pedestrian_open_duration_seconds == 6.0
        assert hub.movement == "opening"
        assert hub.is_operating is True
        assert hub._pedestrian_open_until_monotonic is not None
        hub._cancel_pedestrian_timed_open()

    asyncio.run(run_test())


def test_ps25007a_pedestrian_requires_verified_closed_stopped_start() -> None:
    hub = _hub()
    hub.position = 40

    with pytest.raises(TmtCommandError, match="fully closed and stopped"):
        asyncio.run(hub.async_pedestrian_open())

    hub.position = 0
    hub.is_operating = True
    with pytest.raises(TmtCommandError, match="fully closed and stopped"):
        asyncio.run(hub.async_pedestrian_open())


def test_unrelated_controller_does_not_get_ps25007a_exception() -> None:
    hub = TmtChowHub(
        uuid="test-uuid",
        thing_name="test-thing",
        name="Test gate",
        endpoint="example.invalid",
        certificate_pem="",
        private_key="",
        source_tag="P00317D9",
        product_type="112",
        device_type="PS21053",
    )
    hub._set_controller_type("PS25007A")
    assert hub.configured_controller_type == "PS21053"
    assert hub.pedestrian_strategy == PEDESTRIAN_STRATEGY_NONE
