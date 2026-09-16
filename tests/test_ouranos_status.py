"""Regression tests for opt-in native PS19001 cover status."""

from __future__ import annotations

import asyncio
import json

from custom_components.tmt_chow.const import (
    ATTR_OURANOS_STATUS,
    ATTR_OURANOS_STATUS_RESPONSE,
)
from custom_components.tmt_chow.ouranos_status import OuranosStatusPoller
from custom_components.tmt_chow.protocol import parse_ouranos_status_response
from custom_components.tmt_chow.ps21050d_hub import TmtChowHub


def _response(state: str, position: int, *, result: int = 0) -> str:
    return json.dumps(
        {
            "VER": 1,
            "CMD": "UART",
            "DATA": f"ACK STATUS:{state},{position}\r\n",
            "RESULT": result,
            "ACT": "POST",
        }
    )


def _hub() -> TmtChowHub:
    return TmtChowHub(
        uuid="ABCDEFGHIJKLMNOPQRST",
        thing_name="test-thing",
        name="PS19001 gate",
        endpoint="example.invalid",
        certificate_pem="",
        private_key="",
        source_tag="P9999999",
        product_type="",
        device_type="PS19001",
    )


def test_confirmed_ped_closed_response_maps_to_closed_cover() -> None:
    payload = _response("PED CLOSED", 0)
    parsed = parse_ouranos_status_response(payload)

    assert parsed is not None
    state, status = parsed
    assert state == "PED CLOSED"
    assert status.position == 0
    assert status.is_operating is False
    assert status.is_open_direction is False

    hub = _hub()
    updates: list[bool] = []
    hub.add_listener(lambda: updates.append(True))
    assert hub.apply_ouranos_status_response(payload) is True
    assert hub.position == 0
    assert hub.movement is None
    assert hub.is_operating is False
    assert hub.ouranos_status_available is True
    assert hub.attributes[ATTR_OURANOS_STATUS] == "PED CLOSED"
    assert hub.attributes[ATTR_OURANOS_STATUS_RESPONSE] == payload
    assert updates == [True]


def test_native_opening_and_closing_responses_map_movement() -> None:
    hub = _hub()

    assert hub.apply_ouranos_status_response(_response("OPENING", 42)) is True
    assert (hub.position, hub.movement, hub.is_operating) == (42, "opening", True)

    assert hub.apply_ouranos_status_response(_response("CLOSING", 31)) is True
    assert (hub.position, hub.movement, hub.is_operating) == (31, "closing", True)


def test_native_status_parser_rejects_unsafe_or_malformed_envelopes() -> None:
    assert parse_ouranos_status_response(_response("CLOSED", 0, result=1)) is None
    assert parse_ouranos_status_response(_response("UNKNOWN", 50)) is None
    assert parse_ouranos_status_response(_response("OPENED", 101)) is None
    assert parse_ouranos_status_response("not json") is None


def test_poller_applies_only_a_complete_status_response(monkeypatch) -> None:
    hub = _hub()
    payload = _response("OPENED", 100)

    async def fake_probe(hass, uuid: str, pin_code: str):
        del hass
        assert uuid == hub.uuid
        assert pin_code == "123456"
        return {
            "result": "status_response_received",
            "native": {"status_response": payload},
        }

    monkeypatch.setattr(
        "custom_components.tmt_chow.ouranos_status.async_probe_ouranos_on_ha",
        fake_probe,
    )
    poller = OuranosStatusPoller(object(), hub, "123456")

    assert asyncio.run(poller.async_refresh_once()) is True
    assert poller.last_result == "status_response_received"
    assert hub.position == 100


def test_poller_does_not_apply_partial_probe_result(monkeypatch) -> None:
    hub = _hub()

    async def fake_probe(hass, uuid: str, pin_code: str):
        del hass, uuid, pin_code
        return {"result": "rdt_connected", "native": {}}

    monkeypatch.setattr(
        "custom_components.tmt_chow.ouranos_status.async_probe_ouranos_on_ha",
        fake_probe,
    )
    poller = OuranosStatusPoller(object(), hub, "123456")

    assert asyncio.run(poller.async_refresh_once()) is False
    assert poller.last_result == "rdt_connected"
    assert hub.position is None
