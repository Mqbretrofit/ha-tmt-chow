"""Tests for the single-file unknown-controller routing diagnosis."""

from types import SimpleNamespace

from custom_components.tmt_chow.diagnostics import _controller_route_analysis


def _hub(**overrides):
    values = {
        "configured_controller_type": "PS25142",
        "controller_type": "PS25142",
        "product_type": "112",
        "controller_family": None,
        "ouranos_status_available": False,
        "mqtt_connected": True,
        "model_parameter_schema": None,
        "parameter_write_schema_verified": False,
        "parameter_schema_verified": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_route_report_identifies_ouranos_from_vendor_metadata() -> None:
    report = _controller_route_analysis(
        hub=_hub(),
        uuid_type="1",
        proposal_info={
            "available": True,
            "proposal_type": "PS25142",
            "proposal_version": "B",
            "uart_version": "V3.0",
            "gate_family_hint": "sliding",
            "function_set_available": True,
            "function_labels": ["Open", "Stop", "Close", "PED Open"],
            "parameter_set_count": 18,
            "pedestrian_function_present": True,
            "relay4_present": False,
            "is_tested": True,
        },
        shadow_probe={"result": "rejected"},
        status_probe={"result": "no_response", "observed_payload_count": 0},
        parameter_probe={"result": "no_response", "observed_payload_count": 0},
    )
    assert report["selected_route"]["transport"] == "ouranos_iotc_rdt"
    assert report["selected_route"]["expected_status_command"] == "RS"
    assert report["selected_route"]["expected_parameter_read"] == "RP,1"
    assert report["identity_chain"]["gate_family"] == "sliding"
    assert report["safety"]["movement_commands_sent"] is False
    assert "one read-only native status response is still required" in report[
        "remaining_blockers"
    ]


def test_route_report_identifies_wbt_from_read_only_probe() -> None:
    report = _controller_route_analysis(
        hub=_hub(controller_type="PS99999"),
        uuid_type="5",
        proposal_info={"available": False, "function_set_available": False},
        shadow_probe={"result": "accepted"},
        status_probe={"result": "acknowledged", "observed_payload_count": 1},
        parameter_probe=None,
    )
    assert report["selected_route"]["transport"] == "aws_wbt_mqtt"
    assert report["selected_route"]["runtime_state_source"] == "classic_shadow"
    assert report["implementation_readiness"] == "routing_evidence_collected"
