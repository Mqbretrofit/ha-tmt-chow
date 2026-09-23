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
from custom_components.tmt_chow.hub import TmtCommandError
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
    hub._mqtt._connected.set()

    async def fake_publish(topic: str, payload: str) -> None:
        published.append((topic, payload))
        for expected, future in tuple(hub._waiters):
            if expected == "ACK RS" and not future.done():
                future.set_result("ACK RS:60,64,AA,00,40,00,00,40,00")

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


def test_ps24118_full_open_is_sent_before_status_monitor_starts() -> None:
    hub = _hub()
    events: list[str] = []

    async def fake_command(
        command: str,
        acknowledgement: str,
        *,
        motion_direction: str | None = None,
    ) -> bool:
        assert command == "FULL OPEN"
        assert acknowledgement == "ACK FULL OPEN"
        assert motion_direction == "opening"
        events.append("command")
        return True

    def fake_start_monitor() -> None:
        events.append("monitor")

    hub._async_command = fake_command  # type: ignore[method-assign]
    hub._start_ps24118_status_monitor = fake_start_monitor  # type: ignore[method-assign]

    asyncio.run(hub.async_open())

    assert events == ["command", "monitor"]


def test_ps24118_missing_full_open_ack_falls_back_to_serial_rs_without_resend() -> None:
    hub = _hub()
    hub.position = 0
    hub.is_operating = False
    hub._mqtt._connected.set()
    exchanges: list[tuple[str, str]] = []
    published: list[str] = []

    async def fake_exchange(payload: str, expected: str) -> str:
        exchanges.append((payload, expected))
        if payload == "c=READ STATUS":
            return "ACK STATUS:FULL CLOSED,0"
        if payload.startswith("c=FULL OPEN"):
            try:
                raise TimeoutError
            except TimeoutError as err:
                raise TmtCommandError(
                    "No ACK FULL OPEN acknowledgement",
                    translation_key="no_acknowledgement",
                    translation_placeholders={"acknowledgement": "ACK FULL OPEN"},
                ) from err
        raise AssertionError(f"Unexpected exchange: {payload}")

    async def fake_publish(topic: str, payload: str) -> None:
        assert topic == hub.rx_topic
        published.append(payload)
        for expected, future in tuple(hub._waiters):
            if expected == "ACK RS" and not future.done():
                future.set_result("ACK RS:60,64,EA,20,40,00,00,40,00")

    hub._async_exchange = fake_exchange  # type: ignore[method-assign]
    hub._mqtt.async_publish = fake_publish  # type: ignore[method-assign]

    with patch.object(
        hub_module,
        "_PS24118_ACK_FALLBACK_DELAYS",
        (0.0,),
    ):
        acknowledged = asyncio.run(
            hub._async_command(
                "FULL OPEN",
                "ACK FULL OPEN",
                motion_direction="opening",
            )
        )

    assert acknowledged is False
    assert exchanges == [
        ("c=READ STATUS", "ACK STATUS"),
        ("c=FULL OPEN;src=P9999999", "ACK FULL OPEN"),
    ]
    assert published == ["c=RS;src=P9999999"]
    assert hub.ps24118_command_debug is not None
    assert hub.ps24118_command_debug["result"] == "rs_confirmed_position"


def test_ps24118_rs_waits_for_transaction_lock() -> None:
    hub = _hub()
    hub._mqtt._connected.set()
    published: list[str] = []

    async def fake_publish(topic: str, payload: str) -> None:
        published.append(payload)
        for expected, future in tuple(hub._waiters):
            if expected == "ACK RS" and not future.done():
                future.set_result("ACK RS:60,64,AA,00,40,00,00,40,00")

    hub._mqtt.async_publish = fake_publish  # type: ignore[method-assign]

    async def run() -> None:
        async with hub._transaction_lock:
            task = asyncio.create_task(hub._async_ps24118_request_status())
            await asyncio.sleep(0)
            assert published == []
        assert await task == "ACK RS:60,64,AA,00,40,00,00,40,00"

    asyncio.run(run())

    assert published == ["c=RS;src=P9999999"]


def test_ps24118_full_close_uses_read_status_preflight_before_single_command() -> None:
    hub = _hub()
    hub.position = 100
    hub.is_operating = False
    hub._mqtt._connected.set()
    events: list[tuple[str, str]] = []

    async def fake_exchange(payload: str, expected: str) -> str:
        events.append((payload, expected))
        if payload == "c=READ STATUS":
            return "ACK STATUS:FULL CLOSED,98"
        if payload.startswith("c=FULL CLOSE"):
            return "ACK FULL CLOSE"
        raise AssertionError(f"Unexpected exchange: {payload}")

    hub._async_exchange = fake_exchange  # type: ignore[method-assign]

    acknowledged = asyncio.run(
        hub._async_command(
            "FULL CLOSE",
            "ACK FULL CLOSE",
            motion_direction="closing",
        )
    )

    assert acknowledged is True
    assert events == [
        ("c=READ STATUS", "ACK STATUS"),
        ("c=FULL CLOSE;src=P9999999", "ACK FULL CLOSE"),
    ]
    debug = hub.ps24118_command_debug
    assert debug is not None
    assert debug["preflight_read_status_response"] == "ACK STATUS:FULL CLOSED,98"
    assert debug["explicit_ack_received"] is True
    assert debug["explicit_ack_response"] == "ACK FULL CLOSE"
    assert debug["result"] == "explicit_ack"


def test_ps24118_endpoint_jitter_does_not_confirm_missing_close_ack() -> None:
    hub = _hub()
    hub.position = 100
    hub.is_operating = False
    hub._mqtt._connected.set()

    async def fake_exchange(payload: str, expected: str) -> str:
        if payload == "c=READ STATUS":
            return "ACK STATUS:FULL CLOSED,98"
        if payload.startswith("c=FULL CLOSE"):
            try:
                raise TimeoutError
            except TimeoutError as err:
                raise TmtCommandError(
                    "No ACK FULL CLOSE acknowledgement",
                    translation_key="no_acknowledgement",
                    translation_placeholders={"acknowledgement": "ACK FULL CLOSE"},
                ) from err
        raise AssertionError(f"Unexpected exchange: {payload}")

    async def fake_rs() -> str:
        return "ACK RS:60,64,AA,62,40,00,63,40,00"

    hub._async_exchange = fake_exchange  # type: ignore[method-assign]
    hub._async_ps24118_request_status = fake_rs  # type: ignore[method-assign]

    with patch.object(
        hub_module,
        "_PS24118_ACK_FALLBACK_DELAYS",
        (0.0, 0.0),
    ):
        try:
            asyncio.run(
                hub._async_command(
                    "FULL CLOSE",
                    "ACK FULL CLOSE",
                    motion_direction="closing",
                )
            )
        except TmtCommandError as err:
            assert err.translation_key == "no_acknowledgement"
        else:
            raise AssertionError("98/100 endpoint jitter must not confirm movement")

    debug = hub.ps24118_command_debug
    assert debug is not None
    assert debug["result"] == "no_ack_and_no_motion_proof"
    assert len(debug["fallback_rs"]) == 2
    assert all(sample["position"] == 98 for sample in debug["fallback_rs"])
    assert all(sample["position_delta"] == 0 for sample in debug["fallback_rs"])
    assert all(sample["movement_proven"] is False for sample in debug["fallback_rs"])


def test_ps24118_meaningful_position_delta_can_confirm_missing_close_ack() -> None:
    hub = _hub()
    hub.position = 100
    hub.is_operating = False
    hub._mqtt._connected.set()

    async def fake_exchange(payload: str, expected: str) -> str:
        if payload == "c=READ STATUS":
            return "ACK STATUS:FULL CLOSED,98"
        if payload.startswith("c=FULL CLOSE"):
            try:
                raise TimeoutError
            except TimeoutError as err:
                raise TmtCommandError(
                    "No ACK FULL CLOSE acknowledgement",
                    translation_key="no_acknowledgement",
                    translation_placeholders={"acknowledgement": "ACK FULL CLOSE"},
                ) from err
        raise AssertionError(f"Unexpected exchange: {payload}")

    async def fake_rs() -> str:
        return "ACK RS:60,64,AA,5A,40,00,63,40,00"

    hub._async_exchange = fake_exchange  # type: ignore[method-assign]
    hub._async_ps24118_request_status = fake_rs  # type: ignore[method-assign]

    with patch.object(
        hub_module,
        "_PS24118_ACK_FALLBACK_DELAYS",
        (0.0,),
    ):
        acknowledged = asyncio.run(
            hub._async_command(
                "FULL CLOSE",
                "ACK FULL CLOSE",
                motion_direction="closing",
            )
        )

    assert acknowledged is False
    debug = hub.ps24118_command_debug
    assert debug is not None
    assert debug["result"] == "rs_confirmed_position"
    assert debug["fallback_rs"][0]["normalized_position"] == 90
    assert debug["fallback_rs"][0]["position_delta"] == -10
    assert debug["fallback_rs"][0]["movement_proven"] is True
