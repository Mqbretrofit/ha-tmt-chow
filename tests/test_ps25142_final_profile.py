"""Regression tests for the final PS25142 OURANOS profile."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from custom_components.tmt_chow.diagnostics import _inspect_parameter_payload
from custom_components.tmt_chow.ps21050d_hub import TmtChowHub
from custom_components.tmt_chow.ps25142_parameters import (
    PARAMETER_COUNT,
    PROPOSAL_OPTION_COUNTS,
    PS25142_PARAMETERS,
    encode_parameter_write,
    parse_parameter_response,
    validate_wire_values,
)

_VALUES = (1, 3, 0, 3, 3, 3, 11, 1, 0, 1, 0, 2, 3, 0, 0, 0, 0, 1)
_BODY = ",".join(map(str, _VALUES))
_ISSUE51_VALUES = (1, 8, 0, 3, 0, 1, 5, 0, 0, 0, 0, 2, 3, 0, 0, 0, 1, 1)
_ISSUE51_BODY = ",".join(map(str, _ISSUE51_VALUES))
_ROOT = Path(__file__).resolve().parents[1]


def _hub() -> TmtChowHub:
    return TmtChowHub(
        uuid="ABCDEFGHIJKLMNOPQRST",
        thing_name="test-thing",
        name="PS25142 gate",
        endpoint="example.invalid",
        certificate_pem="",
        private_key="",
        source_tag="P9999999",
        product_type="112",
        device_type="PS25142",
    )


def test_ps25142_proposal_b_parameter_definition_is_exactly_18_slots() -> None:
    assert PARAMETER_COUNT == len(PS25142_PARAMETERS) == 18
    assert tuple(len(item.options) for item in PS25142_PARAMETERS) == (
        PROPOSAL_OPTION_COUNTS
    )
    assert PS25142_PARAMETERS[-1].key == "power_saving_mode"
    assert validate_wire_values(_VALUES) == _VALUES


def test_ps25142_rp1_parser_accepts_native_uart_envelope() -> None:
    payload = json.dumps(
        {
            "VER": 1,
            "CMD": "UART",
            "RESULT": 0,
            "DATA": f"ACK RP,1:{_BODY};src=PXXXXXXX\r\n",
        }
    )
    assert parse_parameter_response(payload) == _VALUES
    assert encode_parameter_write(_VALUES) == f"WP,1:{_BODY}"


def test_issue51_rp1_without_src_decodes_from_uart_json() -> None:
    payload = json.dumps(
        {
            "VER": 1,
            "CMD": "UART",
            "RESULT": 0,
            "DATA": f"ACK RP,1:{_ISSUE51_BODY}\r\n",
        }
    )

    assert parse_parameter_response(payload) == _ISSUE51_VALUES


def test_issue51_nested_native_response_decodes_and_counts_18_tokens() -> None:
    uart = json.dumps(
        {
            "VER": 1,
            "CMD": "UART",
            "RESULT": 0,
            "DATA": f"ACK RP,1:{_ISSUE51_BODY}\r\n",
        }
    )
    payload = json.dumps(
        {
            "event": "parameter_read",
            "response_received": True,
            "response": uart,
        }
    )

    assert parse_parameter_response(payload) == _ISSUE51_VALUES
    debug = _inspect_parameter_payload(payload)
    assert debug is not None
    assert debug["ack_prefix"] == "ACK RP,1"
    assert debug["token_count"] == 18
    assert debug["tokens"] == [str(value) for value in _ISSUE51_VALUES]


def test_issue51_refresh_populates_ps25142_parameters() -> None:
    hub = _hub()
    payload = json.dumps(
        {
            "VER": 1,
            "CMD": "UART",
            "RESULT": 0,
            "DATA": f"ACK RP,1:{_ISSUE51_BODY}\r\n",
        }
    )

    async def exchange(request: str, acknowledgement: str) -> str:
        assert request == "c=RP,1"
        assert acknowledgement == "ACK RP"
        return payload

    hub._async_exchange = exchange  # type: ignore[method-assign]
    asyncio.run(hub.async_refresh_parameters())

    assert hub.parameters == _ISSUE51_VALUES


def test_ps25142_hub_exposes_guarded_full_frame_parameter_support() -> None:
    hub = _hub()
    assert hub.controller_type == "PS25142"
    assert hub.controller_family == "sliding"
    assert hub.parameter_model_type == "PS25142"
    assert hub.parameter_model_source == "ps25142_proposal_b_wire18"
    assert hub.parameter_schema_verified is True
    assert hub.parameter_write_schema_verified is True
    assert hub.supports_parameters is True
    assert hub.may_probe_parameters is True


def test_ps25142_write_is_read_write_full_readback_without_retry() -> None:
    hub = _hub()
    updated = list(_VALUES)
    updated[17] = 0
    expected = tuple(updated)
    expected_body = ",".join(map(str, expected))
    calls: list[tuple[str, str]] = []

    async def exchange(payload: str, acknowledgement: str) -> str:
        calls.append((payload, acknowledgement))
        if len(calls) == 1:
            return f'{{"CMD":"UART","RESULT":0,"DATA":"ACK RP,1:{_BODY};src=PXXXXXXX"}}'
        if len(calls) == 2:
            return '{"CMD":"UART","RESULT":0,"DATA":"ACK WP;src=PXXXXXXX"}'
        return (
            '{"CMD":"UART","RESULT":0,"DATA":"ACK RP,1:'
            + expected_body
            + ';src=PXXXXXXX"}'
        )

    hub._async_exchange = exchange  # type: ignore[method-assign]
    asyncio.run(hub.async_set_parameter(17, 0))

    assert calls == [
        ("c=RP,1", "ACK RP"),
        (f"c=WP,1:{expected_body};src=P9999999", "ACK WP"),
        ("c=RP,1", "ACK RP"),
    ]
    assert hub.parameters == expected


def test_native_helper_keeps_v3_parameter_commands_strictly_allowlisted() -> None:
    source = (
        _ROOT / "tools/ouranos_glibc_session_helper.c"
    ).read_text(encoding="utf-8")
    assert 'strcmp(command, "PARAM_READ_V3")' in source
    assert 'pk_command = "RP,1"' in source
    assert 'strncmp(command, "PARAM_WRITE_V3 ", 15)' in source
    assert 'snprintf(write_command_v3, sizeof(write_command_v3), "WP,1:%s"' in source
    assert "valid_v3_parameter_body" in source
    assert "fields == 18" in source
