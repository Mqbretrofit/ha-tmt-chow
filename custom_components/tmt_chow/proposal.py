"""Helpers for TMT Chow AutoProduct cloud proposals.

TMT Chow 3.2.0 can build controllers that are not present in its static model
catalog from a cloud ResponseProposalInfo payload.  Keep the first integration
step deliberately read-only: fetch, normalize, redact, and expose the vendor
metadata without enabling commands or parameter writes from unverified data.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

_PROPOSAL_ID_RE = re.compile(r"\b((?:PS|NP)\d{5})", re.IGNORECASE)
_EXPECTED_PROPOSAL_KEYS = frozenset(
    {
        "proposaltype",
        "proposalver",
        "uartver",
        "gatetype",
        "appver",
        "parameterset",
        "parameterext",
        "fuctionset",  # Vendor spelling used by the Android model.
        "functionset",
        "istested",
    }
)
_SENSITIVE_KEY_PARTS = (
    "email",
    "token",
    "password",
    "secret",
    "private",
    "certificate",
    "authorization",
)
_FUNCTION_VALUE_KEYS = frozenset(
    {
        "name",
        "functionname",
        "function",
        "title",
        "label",
        "key",
        "code",
        "command",
        "cmd",
        "dcmd",  # ResponseProposalInfo.FunctionSet uses dCmd in TMT Chow 3.2.0.
        "value",
    }
)


def proposal_id_for(controller_type: str | None) -> str | None:
    """Return the seven-character cloud proposal id for a controller string.

    TMT Chow 3.2.0 resolves dynamic products by the PS/NP proposal id rather
    than by a dedicated product class.  A suffixed model such as PS21053C maps
    to the base seven-character proposal id PS21053.
    """
    text = (controller_type or "").strip().upper()
    match = _PROPOSAL_ID_RE.search(text)
    return match.group(1).upper() if match else None


def _key_lookup(data: Mapping[str, Any], *names: str) -> Any:
    wanted = {name.casefold() for name in names}
    for key, value in data.items():
        if str(key).casefold() in wanted:
            return value
    return None


def _looks_like_proposal(data: Mapping[str, Any]) -> bool:
    return any(str(key).casefold() in _EXPECTED_PROPOSAL_KEYS for key in data)


def normalize_proposal_payload(payload: Any) -> dict[str, Any] | None:
    """Return the ResponseProposalInfo-like dictionary from a REST response."""
    if not isinstance(payload, Mapping):
        return None

    root = dict(payload)
    if _looks_like_proposal(root):
        return root

    for key in ("data", "result", "proposal", "response"):
        nested = _key_lookup(root, key)
        if isinstance(nested, Mapping) and _looks_like_proposal(nested):
            return dict(nested)

    # Preserve an object response even when a future firmware/app adds a new
    # schema.  The diagnostics can then show the unknown structure instead of
    # silently discarding useful vendor evidence.
    return root


def proposal_function_set(proposal: Mapping[str, Any] | None) -> Any:
    """Return the vendor FunctionSet value, including its historic typo."""
    if not proposal:
        return None
    return _key_lookup(proposal, "fuctionSet", "functionSet", "function_set")


def proposal_parameter_set(proposal: Mapping[str, Any] | None) -> Any:
    """Return the vendor ParameterSet value."""
    if not proposal:
        return None
    return _key_lookup(proposal, "parameterSet", "parameter_set")


def proposal_parameter_ext(proposal: Mapping[str, Any] | None) -> Any:
    """Return the vendor ParameterExt value."""
    if not proposal:
        return None
    return _key_lookup(proposal, "parameterExt", "parameter_ext")


def _container_count(value: Any) -> int | None:
    if isinstance(value, (list, tuple, set, frozenset, Mapping)):
        return len(value)
    return None


def _collect_function_labels(value: Any, output: set[str]) -> None:
    if isinstance(value, str):
        clean = value.strip()
        if clean:
            output.add(clean)
        return

    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key).strip()
            key_folded = key_text.casefold()
            if key_folded in _FUNCTION_VALUE_KEYS and isinstance(item, str):
                clean = item.strip()
                if clean:
                    output.add(clean)
            elif isinstance(item, (Mapping, list, tuple, set, frozenset)):
                _collect_function_labels(item, output)
        return

    if isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            _collect_function_labels(item, output)


def proposal_function_labels(proposal: Mapping[str, Any] | None) -> tuple[str, ...]:
    """Return stable human-readable labels found inside FunctionSet."""
    labels: set[str] = set()
    _collect_function_labels(proposal_function_set(proposal), labels)
    return tuple(sorted(labels, key=str.casefold))


def _has_label(labels: tuple[str, ...], *needles: str) -> bool:
    normalized = {label.casefold().replace("_", " ") for label in labels}
    for needle in needles:
        wanted = needle.casefold().replace("_", " ")
        if any(wanted in label for label in normalized):
            return True
    return False


def proposal_gate_family(proposal: Mapping[str, Any] | None) -> str | None:
    """Return a conservative textual gate-family hint, if the vendor gives one."""
    if not proposal:
        return None
    value = _key_lookup(proposal, "gateType", "gate_type")
    if not isinstance(value, str):
        return None
    folded = value.casefold()
    # Vendor cloud proposals can use localized gate names.  PS25142 reports
    # Traditional Chinese 橫拉門 (and some endpoints use simplified 横拉门), both
    # meaning a horizontally sliding gate.
    if "slid" in folded or "橫拉門" in value or "横拉门" in value:
        return "sliding"
    if "swing" in folded:
        return "swing"
    if "garage" in folded:
        return "garage"
    return None


def proposal_summary(proposal: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return a compact, diagnostics-safe summary of one cloud proposal."""
    if not proposal:
        return {
            "available": False,
            "function_set_available": False,
            "function_labels": [],
        }

    labels = proposal_function_labels(proposal)
    function_set = proposal_function_set(proposal)
    parameter_set = proposal_parameter_set(proposal)
    parameter_ext = proposal_parameter_ext(proposal)

    return {
        "available": True,
        "proposal_type": _key_lookup(proposal, "proposalType", "proposal_type"),
        "proposal_version": _key_lookup(proposal, "proposalVer", "proposal_version"),
        "uart_version": _key_lookup(proposal, "uartVer", "uartVersion", "uart_version"),
        "gate_type": _key_lookup(proposal, "gateType", "gate_type"),
        "gate_family_hint": proposal_gate_family(proposal),
        "app_version": _key_lookup(proposal, "appVer", "appVersion", "app_version"),
        "is_tested": _key_lookup(proposal, "isTested", "tested", "is_tested"),
        "function_set_available": function_set is not None,
        "function_count": _container_count(function_set),
        "function_labels": list(labels),
        "parameter_set_count": _container_count(parameter_set),
        "parameter_ext_count": _container_count(parameter_ext),
        "pedestrian_function_present": _has_label(labels, "PED Open", "Pedestrian"),
        "relay1_present": _has_label(labels, "Relay 1", "RELAY1"),
        "relay2_present": _has_label(labels, "Relay 2", "RELAY2"),
        "relay3_present": _has_label(labels, "Relay 3", "RELAY3"),
        "relay4_present": _has_label(labels, "Relay 4", "RELAY4"),
        "light_function_present": _has_label(labels, "Light"),
        "external_function_present": _has_label(labels, "External", "Ext"),
    }


def redact_proposal_payload(value: Any) -> Any:
    """Recursively redact personal/credential-like fields from diagnostics."""
    if isinstance(value, Mapping):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            folded = key_text.casefold()
            if any(part in folded for part in _SENSITIVE_KEY_PARTS):
                redacted[key_text] = "<redacted>"
            else:
                redacted[key_text] = redact_proposal_payload(item)
        return redacted
    if isinstance(value, list):
        return [redact_proposal_payload(item) for item in value]
    if isinstance(value, tuple):
        return [redact_proposal_payload(item) for item in value]
    return value
