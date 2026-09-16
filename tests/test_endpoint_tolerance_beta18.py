"""Regression tests for endpoint tolerance applied only after motor stop."""

from __future__ import annotations

from custom_components.tmt_chow.protocol import GateStatus
from custom_components.tmt_chow.ps25007a_hub import TmtChowHub


def _hub() -> TmtChowHub:
    return TmtChowHub(
        uuid="test-uuid",
        thing_name="test-thing",
        name="Test gate",
        endpoint="example.invalid",
        certificate_pem="",
        private_key="",
        source_tag="P9999999",
        product_type="112",
        device_type="PS21053C",
    )


def test_live_two_percent_stays_closing_while_motor_is_running() -> None:
    hub = _hub()
    hub.position = 10
    hub.movement = "closing"
    hub.is_operating = True

    hub._apply_position(5)
    assert hub.position == 5
    assert hub.is_operating is True
    assert hub.movement == "closing"

    hub._apply_position(2)
    assert hub.position == 2
    assert hub.is_operating is True
    assert hub.movement == "closing"


def test_stopped_two_percent_is_tolerated_as_closed() -> None:
    hub = _hub()
    hub.position = 2
    hub.movement = "closing"
    hub.is_operating = True

    hub._apply_status(
        GateStatus(
            position=2,
            is_operating=False,
            is_open_direction=False,
            battery_percent=90,
        )
    )

    assert hub.position == 0
    assert hub.is_operating is False
    assert hub.movement is None


def test_live_ninety_eight_percent_stays_opening_while_motor_is_running() -> None:
    hub = _hub()
    hub.position = 90
    hub.movement = "opening"
    hub.is_operating = True

    hub._apply_position(95)
    assert hub.position == 95
    assert hub.is_operating is True
    assert hub.movement == "opening"

    hub._apply_position(98)
    assert hub.position == 98
    assert hub.is_operating is True
    assert hub.movement == "opening"


def test_stopped_ninety_eight_percent_is_tolerated_as_open() -> None:
    hub = _hub()
    hub.position = 98
    hub.movement = "opening"
    hub.is_operating = True

    hub._apply_status(
        GateStatus(
            position=98,
            is_operating=False,
            is_open_direction=True,
            battery_percent=90,
        )
    )

    assert hub.position == 100
    assert hub.is_operating is False
    assert hub.movement is None


def test_exact_live_endpoint_still_finishes_motion() -> None:
    hub = _hub()
    hub.position = 2
    hub.movement = "closing"
    hub.is_operating = True

    hub._apply_position(0)

    assert hub.position == 0
    assert hub.is_operating is False
    assert hub.movement is None
