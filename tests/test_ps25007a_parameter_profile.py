"""Regression tests for the verified PS25007 -> PS25007A parameter profile."""

from __future__ import annotations

import asyncio

from custom_components.tmt_chow.hub import TmtCommandError
from custom_components.tmt_chow.parameters import PARAMETERS
from custom_components.tmt_chow.pedestrian import PEDESTRIAN_STRATEGY_NONE
from custom_components.tmt_chow.ps25007a_hub import TmtChowHub
from custom_components.tmt_chow.ps25007a_parameters import (
    PARAMETER_COUNT,
    PROPOSAL_OPTION_COUNTS,
    encode_parameter_write,
    parse_parameter_response,
    validate_wire_values,
)

_OBSERVED_VALUES = (1, 3, 0, 3, 3, 3, 11, 1, 0, 1, 0, 2, 3, 0, 0, 0, 0)
_OBSERVED_BODY = ",".join(map(str, _OBSERVED_VALUES))


def _hub(device_type: str = "PS25007") -> TmtChowHub:
    return TmtChowHub(
        uuid="test-uuid",
        thing_name="test-thing",
        name="Test gate",
        endpoint="example.invalid",
        certificate_pem="",
        private_key="",
        source_tag="P9999999",
        product_type="112",
        device_type=device_type,
    )


def test_ps25007_proposal_matches_verified_17_value_option_profile() -> None:
    assert PARAMETER_COUNT == len(PARAMETERS) == 17
    assert tuple(len(definition.options) for definition in PARAMETERS) == PROPOSAL_OPTION_COUNTS
    assert PARAMETERS[6].key == "overcurrent"
    assert PARAMETERS[6].options == tuple(f"amp_{value}" for value in range(2, 14))
    assert validate_wire_values(_OBSERVED_VALUES) == _OBSERVED_VALUES


def test_ps25007a_parser_accepts_live_ack_and_shadow_body() -> None:
    assert parse_parameter_response(_OBSERVED_BODY) == _OBSERVED_VALUES
    assert parse_parameter_response(f"ACK RP,1:{_OBSERVED_BODY}") == _OBSERVED_VALUES
    assert parse_parameter_response(f"ACK RP:{_OBSERVED_BODY}") == _OBSERVED_VALUES
    assert parse_parameter_response("ACK RP,1:1,2,3") is None
    assert parse_parameter_response(f"NAK RP,1:{_OBSERVED_BODY}") is None


def test_ps25007_startup_profile_is_readable_but_not_writable_before_live_identity() -> None:
    hub = _hub()

    assert hub.controller_type == "PS25007"
    assert hub.configured_controller_type == "PS25007"
    assert hub.controller_family == "sliding"
    assert hub.parameter_model_type == "PS25007A"
    assert hub.parameter_model_source == "ps25007_proposal_wire17_pending_live"
    assert hub.model_parameter_schema is not None
    assert len(hub.model_parameter_schema) == 17
    assert hub.may_probe_parameters is True
    assert hub.parameter_write_schema_verified is False
    assert hub.supports_parameters is False
    assert hub.pedestrian_strategy == PEDESTRIAN_STRATEGY_NONE


def test_live_ps25007a_identity_enables_verified_parameter_writes_but_not_ped_open() -> None:
    hub = _hub()
    hub._set_controller_type("PS25007A")

    assert hub.controller_type == "PS25007A"
    assert hub.parameter_model_type == "PS25007A"
    assert hub.parameter_model_source == "ps25007a_proposal_wire17_verified"
    assert hub.parameter_write_schema_verified is True
    assert hub.supports_parameters is True
    assert hub._decode_parameter_response(_OBSERVED_BODY) == _OBSERVED_VALUES
    assert hub.pedestrian_strategy == PEDESTRIAN_STRATEGY_NONE


def test_ps25007a_write_reads_first_writes_once_and_verifies_complete_frame() -> None:
    hub = _hub()
    hub._set_controller_type("PS25007A")

    updated = list(_OBSERVED_VALUES)
    updated[6] = 10
    updated_values = tuple(updated)
    updated_body = ",".join(map(str, updated_values))
    expected_command = encode_parameter_write(updated_values)
    assert expected_command == f"WP,1:{updated_body}"

    calls: list[tuple[str, str]] = []

    async def fake_exchange(payload: str, expected: str) -> str:
        calls.append((payload, expected))
        if len(calls) == 1:
            return f"ACK RP,1:{_OBSERVED_BODY}"
        if len(calls) == 2:
            assert payload == f"c={expected_command};src=P9999999"
            assert expected == "ACK WP"
            return "ACK WP"
        return f"ACK RP,1:{updated_body}"

    hub._async_exchange = fake_exchange  # type: ignore[method-assign]
    asyncio.run(hub.async_set_parameter(6, 10))

    assert calls == [
        ("c=RP,1", "ACK RP,1"),
        (f"c={expected_command};src=P9999999", "ACK WP"),
        ("c=RP,1", "ACK RP,1"),
    ]
    assert hub.parameters == updated_values


def test_ps25007a_write_rejects_any_collateral_readback_change() -> None:
    hub = _hub()
    hub._set_controller_type("PS25007A")
    calls: list[tuple[str, str]] = []

    requested = list(_OBSERVED_VALUES)
    requested[6] = 10
    collateral = requested.copy()
    collateral[1] = 4

    async def fake_exchange(payload: str, expected: str) -> str:
        calls.append((payload, expected))
        if len(calls) == 1:
            return f"ACK RP,1:{_OBSERVED_BODY}"
        if len(calls) == 2:
            return "ACK WP"
        return "ACK RP,1:" + ",".join(map(str, collateral))

    hub._async_exchange = fake_exchange  # type: ignore[method-assign]

    try:
        asyncio.run(hub.async_set_parameter(6, 10))
    except TmtCommandError as err:
        assert err.translation_key == "parameter_verification_failed"
    else:
        raise AssertionError("Collateral PS25007A parameter change was accepted")

    assert len(calls) == 3


def test_unrelated_account_model_does_not_gain_ps25007a_write_profile() -> None:
    hub = _hub("PS21053")
    hub._set_controller_type("PS25007A")

    assert hub.configured_controller_type == "PS21053"
    assert hub.parameter_model_type != "PS25007A"
    assert hub.parameter_write_schema_verified is False
    assert hub.pedestrian_strategy == PEDESTRIAN_STRATEGY_NONE
