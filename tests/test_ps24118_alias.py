"""Regression coverage for PS24118 / PS24118C standby-state handling."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import custom_components.tmt_chow.ps21050d_hub as hub_module
from custom_components.tmt_chow.controller_types import (
    CAPABILITY_PEDESTRIAN,
    FAMILY_SWING,
)
from custom_components.tmt_chow.hub import TmtCommandError
from custom_components.tmt_chow.pedestrian import PEDESTRIAN_STRATEGY_PED_OPEN
from custom_components.tmt_chow.ps21050d_hub import TmtChowHub


def _hub(source_tag: str = "P9999999") -> TmtChowHub:
    return TmtChowHub(
        uuid="test-uuid",
        thing_name="test-thing",
        name="PS24118 test gate",
        endpoint="example.invalid",
        certificate_pem="",
        private_key="",
        source_tag=source_tag,
        product_type="197",
        device_type="PS24118",
    )


def test_ps24118_reuses_only_p190u_family_and_pedestrian_capability() -> None:
    hub = _hub()

    assert hub.controller_type == "PS24118"
    assert hub.controller_family == FAMILY_SWING
    assert CAPABILITY_PEDESTRIAN in hub.controller_capabilities
    assert hub.pedestrian_strategy == PEDESTRIAN_STRATEGY_PED_OPEN

    # P190U evidence is capability-only: never borrow its parameter write path.
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


def test_ps24118_requests_optional_rx_observation_only_for_exact_profile() -> None:
    hub = _hub()
    assert hub.rx_topic in hub._mqtt._topics
    assert hub.rx_topic in hub._mqtt._optional_topics

    other = TmtChowHub(
        uuid="other-uuid",
        thing_name="other-thing",
        name="Other gate",
        endpoint="example.invalid",
        certificate_pem="",
        private_key="",
        source_tag="P9999999",
        product_type="112",
        device_type="PS21050",
    )
    assert other.rx_topic not in other._mqtt._topics
    assert other.rx_topic not in other._mqtt._optional_topics


def test_ps24118_learns_non_default_vendor_source_tag_from_rx() -> None:
    hub = _hub()
    learned: list[str] = []
    hub.set_source_tag_update_callback(learned.append)

    asyncio.run(
        hub._async_message(
            hub.rx_topic,
            "c=FULL OPEN;src=P00317D9",
        )
    )

    assert hub._source_tag == "P00317D9"
    assert learned == ["P00317D9"]
    debug = hub.ps24118_source_tag_debug
    assert debug is not None
    assert debug["is_default"] is False
    assert debug["format_valid"] is True
    assert debug["origin"] == "vendor_rx_observed"


def test_ps24118_does_not_learn_default_or_overwrite_configured_vendor_tag() -> None:
    hub = _hub()
    learned: list[str] = []
    hub.set_source_tag_update_callback(learned.append)

    hub._learn_ps24118_source_tag("c=RS;src=P9999999")
    assert hub._source_tag == "P9999999"
    assert learned == []

    configured = _hub("P00317D9")
    configured._learn_ps24118_source_tag("c=FULL OPEN;src=P00ABCDE")
    assert configured._source_tag == "P00317D9"
    assert configured.ps24118_source_tag_debug is not None
    assert configured.ps24118_source_tag_debug["origin"] == "configured_vendor"


def test_ps24118_learned_source_tag_is_used_without_preflight_or_rearm() -> None:
    hub = _hub()
    hub._learn_ps24118_source_tag("c=FULL OPEN;src=P00317D9")
    hub.position = 100
    hub.is_operating = False
    events: list[tuple[str, str]] = []

    async def fake_exchange(payload: str, expected: str) -> str:
        events.append((payload, expected))
        return "ACK FULL CLOSE"

    hub._async_exchange = fake_exchange  # type: ignore[method-assign]

    acknowledged = asyncio.run(
        hub._async_command(
            "FULL CLOSE",
            "ACK FULL CLOSE",
            motion_direction="closing",
        )
    )

    assert acknowledged is True
    assert events == [("c=FULL CLOSE;src=P00317D9", "ACK FULL CLOSE")]
    debug = hub.ps24118_command_debug
    assert debug is not None
    assert debug["source_tag_is_default"] is False
    assert debug["source_tag_format_valid"] is True
    assert debug["source_tag_origin"] == "vendor_rx_observed"
    assert debug["preflight_read_status_response"] is None
    assert "source_tag" not in debug
    assert "rearm" not in debug


def test_ps24118_missing_ack_uses_read_only_rs_without_resending_movement() -> None:
    hub = _hub("P00317D9")
    hub.position = 0
    hub.is_operating = False
    exchanges: list[tuple[str, str]] = []
    rs_reads = 0

    async def fake_exchange(payload: str, expected: str) -> str:
        exchanges.append((payload, expected))
        try:
            raise TimeoutError
        except TimeoutError as err:
            raise TmtCommandError(
                "No ACK FULL OPEN acknowledgement",
                translation_key="no_acknowledgement",
                translation_placeholders={"acknowledgement": "ACK FULL OPEN"},
            ) from err

    async def fake_rs() -> str:
        nonlocal rs_reads
        rs_reads += 1
        return "ACK RS:60,64,EA,A0,40,00,00,40,00"

    hub._async_exchange = fake_exchange  # type: ignore[method-assign]
    hub._async_ps24118_request_status = fake_rs  # type: ignore[method-assign]

    with patch.object(hub_module, "_PS24118_ACK_FALLBACK_DELAYS", (0.0,)):
        acknowledged = asyncio.run(
            hub._async_command(
                "FULL OPEN",
                "ACK FULL OPEN",
                motion_direction="opening",
            )
        )

    assert acknowledged is False
    assert exchanges == [("c=FULL OPEN;src=P00317D9", "ACK FULL OPEN")]
    assert rs_reads == 1
    assert hub.ps24118_command_debug is not None
    assert hub.ps24118_command_debug["result"] == "rs_confirmed_operating"


def test_ps24118_endpoint_jitter_does_not_confirm_missing_close_ack() -> None:
    hub = _hub("P00317D9")
    hub.position = 100
    hub.is_operating = False

    async def fake_exchange(payload: str, expected: str) -> str:
        try:
            raise TimeoutError
        except TimeoutError as err:
            raise TmtCommandError(
                "No ACK FULL CLOSE acknowledgement",
                translation_key="no_acknowledgement",
                translation_placeholders={"acknowledgement": "ACK FULL CLOSE"},
            ) from err

    async def fake_rs() -> str:
        return "ACK RS:60,64,AA,62,40,00,63,40,00"

    hub._async_exchange = fake_exchange  # type: ignore[method-assign]
    hub._async_ps24118_request_status = fake_rs  # type: ignore[method-assign]

    with patch.object(hub_module, "_PS24118_ACK_FALLBACK_DELAYS", (0.0, 0.0)):
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
    hub = _hub("P00317D9")
    hub.position = 100
    hub.is_operating = False

    async def fake_exchange(payload: str, expected: str) -> str:
        try:
            raise TimeoutError
        except TimeoutError as err:
            raise TmtCommandError(
                "No ACK FULL CLOSE acknowledgement",
                translation_key="no_acknowledgement",
                translation_placeholders={"acknowledgement": "ACK FULL CLOSE"},
            ) from err

    async def fake_rs() -> str:
        return "ACK RS:60,64,AA,5A,40,00,63,40,00"

    hub._async_exchange = fake_exchange  # type: ignore[method-assign]
    hub._async_ps24118_request_status = fake_rs  # type: ignore[method-assign]

    with patch.object(hub_module, "_PS24118_ACK_FALLBACK_DELAYS", (0.0,)):
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


def test_ps24118_stale_shadow_status_cannot_override_live_state() -> None:
    hub = _hub()
    hub.position = 100
    hub.is_operating = False
    hub.movement = None

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
    hub = _hub("P00317D9")
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
        (hub.rx_topic, "c=RS;src=P00317D9"),
        (hub.rx_topic, "c=RS;src=P00317D9"),
        (hub.rx_topic, "c=RS;src=P00317D9"),
    ]
