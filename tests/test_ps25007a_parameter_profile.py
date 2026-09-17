"""Regression tests for the verified PS25007 -> PS25007A parameter profile."""

from __future__ import annotations

import asyncio

from custom_components.tmt_chow.parameters import PARAMETERS
from custom_components.tmt_chow.pedestrian import PEDESTRIAN_STRATEGY_PED_OPEN
from custom_components.tmt_chow.ps21050d_hub import TmtChowHub
from custom_components.tmt_chow.ps25007a_parameters import (
    PARAMETER_COUNT,
    PROPOSAL_OPTION_COUNTS,
    encode_parameter_write,
    parse_parameter_response,
    validate_wire_values,
)

_VALUES = (1, 3, 0, 3, 3, 3, 11, 1, 0, 1, 0, 2, 3, 0, 0, 0, 0)
_BODY = ",".join(map(str, _VALUES))


def _hub(device_type: str = "PS25007") -> TmtChowHub:
    return TmtChowHub(
        uuid="test-uuid",
        thing_name="test-thing",
        name="Test gate",
        endpoint="example.invalid",
        certificate_pem="",
        private_key="",
        source_tag="P00317D9",
        product_type="112",
        device_type=device_type,
    )


def test_verified_ps25007a_frame_matches_reference_schema() -> None:
    assert PARAMETER_COUNT == len(PARAMETERS) == 17
    assert tuple(len(item.options) for item in PARAMETERS) == PROPOSAL_OPTION_COUNTS
    assert validate_wire_values(_VALUES) == _VALUES
    assert parse_parameter_response(_BODY) == _VALUES
    assert parse_parameter_response(f"ACK RP,1:{_BODY}") == _VALUES


def test_ps25007_requires_live_ps25007a_before_writes() -> None:
    hub = _hub()
    assert hub.parameter_model_type == "PS25007A"
    assert hub.parameter_model_source == "ps25007_proposal_wire17_pending_live"
    assert hub.model_parameter_schema is not None
    assert len(hub.model_parameter_schema) == 17
    assert hub.may_probe_parameters is True
    assert hub.parameter_write_schema_verified is False

    hub._set_controller_type("PS25007A")
    assert hub.controller_family == "sliding"
    assert hub.parameter_model_source == "ps25007a_proposal_wire17_verified"
    assert hub.parameter_write_schema_verified is True
    assert hub.supports_parameters is True
    assert hub.pedestrian_strategy == PEDESTRIAN_STRATEGY_PED_OPEN


def test_ps25007a_write_reads_writes_once_and_verifies_full_frame() -> None:
    hub = _hub()
    hub._set_controller_type("PS25007A")
    updated = list(_VALUES)
    updated[6] = 10
    expected = tuple(updated)
    expected_body = ",".join(map(str, expected))
    calls: list[tuple[str, str]] = []

    async def exchange(payload: str, acknowledgement: str) -> str:
        calls.append((payload, acknowledgement))
        if len(calls) == 1:
            return f"ACK RP,1:{_BODY}"
        if len(calls) == 2:
            return "ACK WP"
        return f"ACK RP,1:{expected_body}"

    hub._async_exchange = exchange  # type: ignore[method-assign]
    asyncio.run(hub.async_set_parameter(6, 10))

    write = encode_parameter_write(expected)
    assert calls == [
        ("c=RP,1", "ACK RP,1"),
        (f"c={write};src=P00317D9", "ACK WP"),
        ("c=RP,1", "ACK RP,1"),
    ]
    assert hub.parameters == expected


def test_unrelated_controller_does_not_gain_ps25007a_profile() -> None:
    hub = _hub("PS21053")
    hub._set_controller_type("PS25007A")
    assert hub.parameter_model_type != "PS25007A"
    assert hub.parameter_write_schema_verified is False
