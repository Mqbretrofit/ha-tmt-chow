"""Pedestrian/partial-opening command strategy and safety guards."""

from __future__ import annotations

from collections.abc import Collection
from typing import Final

from .controller_types import CAPABILITY_PEDESTRIAN, normalize_controller_type

PEDESTRIAN_STRATEGY_NONE: Final = "none"
PEDESTRIAN_STRATEGY_PED_OPEN: Final = "ped_open"
PEDESTRIAN_STRATEGY_RELAY4: Final = "relay4"

# Real-hardware safety evidence from PS25007A (P500BU,PS25007A,V02): a direct
# PED OPEN moved the gate but returned no ACK PED OPEN, and the next FULL CLOSE
# executed with inverted direction until the vendor app recovered the board.
# Keep this explicit deny-list even if a future capability import accidentally
# classifies the model as pedestrian-capable.
UNSAFE_DIRECT_PED_OPEN_CONTROLLERS: Final = frozenset({"PS25007A"})

# TMT Chow 3.1.4 AutoProduct supports a separate Relay 4 pedestrian path, but
# no concrete controller is enabled here until its cloud FunctionSet/real
# hardware path is verified. An empty allow-list makes accidental RELAY4
# transmission impossible.
RELAY4_PEDESTRIAN_CONTROLLERS: Final = frozenset()


def direct_ped_open_blocked(controller_type: str | None) -> bool:
    """Return whether direct PED OPEN is explicitly unsafe for this controller."""
    return normalize_controller_type(controller_type) in UNSAFE_DIRECT_PED_OPEN_CONTROLLERS


def pedestrian_strategy_for(
    controller_type: str | None,
    capabilities: Collection[str],
) -> str:
    """Return the safe command strategy for pedestrian/partial opening."""
    normalized = normalize_controller_type(controller_type)
    if normalized in UNSAFE_DIRECT_PED_OPEN_CONTROLLERS:
        return PEDESTRIAN_STRATEGY_NONE
    if normalized in RELAY4_PEDESTRIAN_CONTROLLERS:
        return PEDESTRIAN_STRATEGY_RELAY4
    if CAPABILITY_PEDESTRIAN in capabilities:
        return PEDESTRIAN_STRATEGY_PED_OPEN
    return PEDESTRIAN_STRATEGY_NONE


def pedestrian_strategy_reason(
    controller_type: str | None,
    capabilities: Collection[str],
) -> str:
    """Return a compact diagnostics reason for the selected strategy."""
    normalized = normalize_controller_type(controller_type)
    if normalized in UNSAFE_DIRECT_PED_OPEN_CONTROLLERS:
        return "direct_ped_open_blocked_real_hardware"
    if normalized in RELAY4_PEDESTRIAN_CONTROLLERS:
        return "explicit_relay4_mapping"
    if CAPABILITY_PEDESTRIAN in capabilities:
        return "apk_pedestrian_capability"
    return "no_verified_pedestrian_command"
