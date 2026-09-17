"""Regression coverage for the live-verified PS22087 / PS22087B alias."""

from __future__ import annotations

import asyncio

from custom_components.tmt_chow.const import ATTR_DEV_PARAM
from custom_components.tmt_chow.ps21050d_hub import TmtChowHub
from custom_components.tmt_chow.ps22087b_parameters import (
    PARAMETERS,
    encode_parameter_write,
    parse_parameter_response,
)
from custom_components.tmt_chow.select import TmtP710UParameterSelect

_VALUES = (1, 2, 0, 1, 2, 1, 3, 3, 1, 4, 77, 5, 88, 4, 1)
_BODY = ",".join(map(str, _VALUES))


def _hub() -> TmtChowHub:
    return TmtChowHub(
        uuid="123456789012345678901234",
        thing_name="thing",
        name="PS22087B gate",
        endpoint="example.iot",
        certificate_pem="certificate",
        private_key="key",
        source_tag="P1234567",
        product_type="118",
        device_type="PS22087",
    )


def test_ps22087_waits_for_exact_live_alias() -> None:
    hub = _hub()
    assert hub.controller_type == "PS22087"
    assert hub.parameter_model_type is None
    assert hub.parameter_write_schema_verified is False

    hub._set_controller_type("PS22087B")
    assert hub.parameter_model_type == "PS22087B"
    assert hub.parameter_model_source == "ps22087b_p710u_wire15_verified"
    assert len(hub.model_parameter_schema or ()) == 15
    assert hub.parameter_schema_verified is True
    assert hub.parameter_write_schema_verified is True


def test_ps22087_wire15_parser_and_reserved_fields() -> None:
    assert parse_parameter_response(f"ACK RP,1:{_BODY}") == _VALUES
    assert parse_parameter_response(f"ACK RP,1:{_BODY},0") is None
    assert encode_parameter_write(_VALUES) == f"WP,1:{_BODY}"
    assert PARAMETERS[10].writable is False
    assert PARAMETERS[12].writable is False


def test_ps22087_preserves_hardware_beta_entity_ids() -> None:
    entity = TmtP710UParameterSelect(_hub(), 7, PARAMETERS[7])
    assert entity.unique_id == "123456789012345678901234_p710u_parameter_f8"


def test_ps22087_write_preserves_other_fourteen_fields() -> None:
    hub = _hub()
    hub._set_controller_type("PS22087B")
    updated = list(_VALUES)
    updated[7] = 2
    expected = tuple(updated)
    responses = iter(
        (
            f"ACK RP,1:{_BODY}",
            "ACK WP,1",
            "ACK RP,1:" + ",".join(map(str, expected)),
        )
    )
    calls: list[str] = []

    async def exchange(command: str, acknowledgement: str) -> str:
        calls.append(command)
        return next(responses)

    hub._async_exchange = exchange  # type: ignore[method-assign]
    asyncio.run(hub.async_set_parameter(7, 2))

    assert calls == [
        "c=RP,1",
        "c=WP,1:" + ",".join(map(str, expected)) + ";src=P1234567",
        "c=RP,1",
    ]
    assert hub.parameters == expected
    assert hub.attributes[ATTR_DEV_PARAM] == ",".join(map(str, expected))


def test_unrelated_ps22087b_identity_does_not_borrow_profile() -> None:
    hub = TmtChowHub(
        uuid="123456789012345678901234",
        thing_name="thing",
        name="unrelated",
        endpoint="example.iot",
        certificate_pem="certificate",
        private_key="key",
        source_tag="P1234567",
        product_type="118",
        device_type="PS21053",
    )
    hub._set_controller_type("PS22087B")
    assert hub.parameter_model_source != "ps22087b_p710u_wire15_verified"
    assert hub.parameter_write_schema_verified is False
