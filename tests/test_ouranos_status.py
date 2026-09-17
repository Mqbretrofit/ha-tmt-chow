"""Regression tests for opt-in native PS19001 cover status."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import custom_components.tmt_chow.hub as hub_module
from custom_components.tmt_chow.button import (
    TmtOuranosRefreshButton,
)
from custom_components.tmt_chow.button import (
    async_setup_entry as async_setup_buttons,
)
from custom_components.tmt_chow.const import (
    ATTR_OURANOS_STATUS,
    ATTR_OURANOS_STATUS_RESPONSE,
    DOMAIN,
    OURANOS_POLLERS_DATA_KEY,
    OURANOS_STATUS_AVAILABILITY_SECONDS,
)
from custom_components.tmt_chow.ouranos_status import OuranosStatusPoller
from custom_components.tmt_chow.parameter_codec import (
    encode_model_parameter_write,
    parameter_defaults,
)
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


class FakeSession:
    def __init__(self, result: dict) -> None:
        self.result = result
        self.connected = True
        self.read_count = 0
        self.stopped = False

    async def async_read_status(self) -> dict:
        self.read_count += 1
        return self.result

    async def async_stop(self) -> None:
        self.stopped = True
        self.connected = False


class FakeControlSession(FakeSession):
    def __init__(self, parameter_reads: list[str] | None = None) -> None:
        super().__init__({})
        self.commands: list[str] = []
        self.parameter_writes: list[str] = []
        self.parameter_reads = list(parameter_reads or [])

    async def async_gate_command(self, command: str) -> dict:
        self.commands.append(command)
        return {
            "result": "command_response_received",
            "native": {"response": f"ACK {command}"},
        }

    async def async_read_parameters(self) -> dict:
        return {
            "result": "parameter_read_response_received",
            "native": {"response": self.parameter_reads.pop(0)},
        }

    async def async_write_parameters(self, command: str) -> dict:
        self.parameter_writes.append(command)
        return {
            "result": "parameter_write_response_received",
            "native": {"response": "ACK FUNCTION"},
        }


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


def test_ps19001_cover_commands_use_native_session_exactly_once() -> None:
    hub = _hub()
    session = FakeControlSession()
    hub.set_ouranos_native_session(session)

    asyncio.run(hub.async_open())
    asyncio.run(hub.async_close())
    asyncio.run(hub.async_pedestrian_open())
    asyncio.run(hub.async_stop_gate())

    assert session.commands == ["FULL OPEN", "FULL CLOSE", "PED OPEN", "STOP"]


def test_ps19001_parameter_write_reads_writes_once_and_verifies() -> None:
    hub = _hub()
    defaults = parameter_defaults("PS19001")
    assert defaults is not None and len(defaults) == 23
    updated = list(defaults)
    updated[0] = 0

    def response(values: tuple[int, ...]) -> str:
        command = encode_model_parameter_write("PS19001", values)
        return "ACK READ FUNCTION" + command.removeprefix("WRITE FUNCTION")

    session = FakeControlSession(
        [response(defaults), response(tuple(updated))]
    )
    hub.set_ouranos_native_session(session)

    asyncio.run(hub.async_set_parameter(0, 0))

    assert session.parameter_writes == [
        encode_model_parameter_write("PS19001", tuple(updated))
    ]
    assert hub.parameters == tuple(updated)


def test_native_status_parser_rejects_unsafe_or_malformed_envelopes() -> None:
    assert parse_ouranos_status_response(_response("CLOSED", 0, result=1)) is None
    assert parse_ouranos_status_response(_response("UNKNOWN", 50)) is None
    assert parse_ouranos_status_response(_response("OPENED", 101)) is None
    assert parse_ouranos_status_response("not json") is None


def test_poller_applies_only_a_complete_status_response() -> None:
    hub = _hub()
    payload = _response("OPENED", 100)

    session = FakeSession(
        {
            "result": "status_response_received",
            "native": {"response": payload},
        }
    )
    poller = OuranosStatusPoller(object(), hub, "123456", session=session)

    assert asyncio.run(poller.async_refresh_once()) is True
    assert poller.last_result == "status_response_received"
    assert poller.last_attempt_at is not None
    assert poller.last_success_at is not None
    assert poller.consecutive_failures == 0
    assert hub.position == 100
    assert poller.session_connected is True
    assert session.read_count == 1


def test_poller_does_not_apply_partial_probe_result() -> None:
    hub = _hub()

    session = FakeSession({"result": "rdt_connected", "native": {}})
    poller = OuranosStatusPoller(object(), hub, "123456", session=session)

    assert asyncio.run(poller.async_refresh_once()) is False
    assert poller.last_result == "rdt_connected"
    assert poller.last_attempt_at is not None
    assert poller.last_success_at is None
    assert poller.consecutive_failures == 1
    assert hub.position is None


def test_failed_refresh_keeps_last_valid_status_available(monkeypatch) -> None:
    hub = _hub()
    now = 1000.0
    monkeypatch.setattr(hub_module.time, "monotonic", lambda: now)
    assert hub.apply_ouranos_status_response(_response("CLOSED", 0)) is True

    session = FakeSession({"result": "rdt_connected", "native": {}})
    poller = OuranosStatusPoller(object(), hub, "123456", session=session)
    assert asyncio.run(poller.async_refresh_once()) is False

    assert hub.position == 0
    assert hub.ouranos_status_available is True
    assert hub.available is True


def test_poller_stop_always_closes_persistent_session() -> None:
    hub = _hub()
    session = FakeSession({"result": "rdt_connected", "native": {}})
    poller = OuranosStatusPoller(object(), hub, "123456", session=session)

    asyncio.run(poller.async_stop())

    assert session.stopped is True
    assert poller.session_connected is False


def test_native_availability_expires_only_after_extended_grace(monkeypatch) -> None:
    hub = _hub()
    now = 1000.0
    monkeypatch.setattr(hub_module.time, "monotonic", lambda: now)
    assert hub.apply_ouranos_status_response(_response("CLOSED", 0)) is True

    now += OURANOS_STATUS_AVAILABILITY_SECONDS - 1
    assert hub.ouranos_status_available is True
    assert hub.available is True

    now += 2
    assert hub.ouranos_status_available is False
    assert hub.available is False


def test_native_refresh_button_is_added_for_enabled_poller() -> None:
    hub = _hub()

    class SuccessfulPoller:
        last_result = "status_response_received"

        async def async_refresh_once(self) -> bool:
            return True

    poller = SuccessfulPoller()
    hass = SimpleNamespace(
        data={
            DOMAIN: {"entry": hub},
            OURANOS_POLLERS_DATA_KEY: {"entry": poller},
        }
    )
    entry = SimpleNamespace(entry_id="entry")
    entities = []

    asyncio.run(async_setup_buttons(hass, entry, entities.extend))

    refresh_buttons = [
        entity for entity in entities if isinstance(entity, TmtOuranosRefreshButton)
    ]
    assert len(refresh_buttons) == 1
    assert refresh_buttons[0].available is True
    asyncio.run(refresh_buttons[0].async_press())
