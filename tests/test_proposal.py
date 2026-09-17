from custom_components.tmt_chow.proposal import (
    normalize_proposal_payload,
    proposal_function_labels,
    proposal_id_for,
    proposal_summary,
    redact_proposal_payload,
)


def test_proposal_id_for_dynamic_controller() -> None:
    assert proposal_id_for("PS25142") == "PS25142"
    assert proposal_id_for("P500BU,PS25007A,V02") == "PS25007"
    assert proposal_id_for("PS21053C") == "PS21053"
    assert proposal_id_for("P710U") is None


def test_normalize_nested_response_proposal_info() -> None:
    payload = {
        "data": {
            "proposalType": "PS25142",
            "proposalVer": 3,
            "uartVer": 2,
            "gateType": "Sliding Gate",
            "parameterSet": [{"name": "p1"}],
            "parameterExt": [],
            "fuctionSet": [{"functionName": "Relay 4"}],
        }
    }

    proposal = normalize_proposal_payload(payload)

    assert proposal is not None
    assert proposal["proposalType"] == "PS25142"
    assert proposal_summary(proposal)["gate_family_hint"] == "sliding"


def test_function_set_summary_is_read_only_evidence() -> None:
    proposal = {
        "proposalType": "PS25142",
        "fuctionSet": [
            {"functionName": "PED Open"},
            {"functionName": "Relay 1"},
            {"functionName": "Relay 4"},
            {"name": "Light"},
        ],
        "parameterSet": [1, 2, 3],
    }

    labels = proposal_function_labels(proposal)
    summary = proposal_summary(proposal)

    assert "PED Open" in labels
    assert "Relay 4" in labels
    assert summary["function_set_available"] is True
    assert summary["pedestrian_function_present"] is True
    assert summary["relay1_present"] is True
    assert summary["relay4_present"] is True
    assert summary["light_function_present"] is True
    assert summary["parameter_set_count"] == 3


def test_ps25142_proposal_b_uses_dcmd_and_localized_sliding_gate_name() -> None:
    proposal = {
        "proposalType": "PS25142",
        "proposalVer": "B",
        "uartVer": "V3.0",
        "gateType": "橫拉門",
        "parameterSet": [{} for _ in range(18)],
        "parameterExt": [],
        "fuctionSet": [
            {"dCmd": "Open", "sNotifyContent": ["Opening", "Opened"]},
            {"dCmd": "Stop", "sNotifyContent": ["Stopped"]},
            {"dCmd": "Close", "sNotifyContent": ["Closing", "Closed"]},
            {"dCmd": "PED Open", "sNotifyContent": ["PedOpening", "PedOpened"]},
        ],
        "is_tested": True,
    }

    labels = proposal_function_labels(proposal)
    summary = proposal_summary(proposal)

    assert "Open" in labels
    assert "Stop" in labels
    assert "Close" in labels
    assert "PED Open" in labels
    assert summary["gate_family_hint"] == "sliding"
    assert summary["pedestrian_function_present"] is True
    assert summary["parameter_set_count"] == 18


def test_simplified_chinese_sliding_gate_name_is_supported() -> None:
    summary = proposal_summary(
        {"proposalType": "PS25142", "gateType": "横拉门", "fuctionSet": []}
    )
    assert summary["gate_family_hint"] == "sliding"


def test_proposal_redaction_is_recursive() -> None:
    raw = {
        "proposalType": "PS25142",
        "userEmail": "owner@example.com",
        "nested": {
            "accessToken": "secret-token",
            "safe": "keep-me",
        },
    }

    redacted = redact_proposal_payload(raw)

    assert redacted["userEmail"] == "<redacted>"
    assert redacted["nested"]["accessToken"] == "<redacted>"
    assert redacted["nested"]["safe"] == "keep-me"
