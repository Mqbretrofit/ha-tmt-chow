"""Regression coverage for the observed PS20005A controller identity alias."""

from custom_components.tmt_chow.controller_types import (
    CAPABILITY_PEDESTRIAN,
    FAMILY_SWING,
)
from custom_components.tmt_chow.pedestrian import PEDESTRIAN_STRATEGY_PED_OPEN
from custom_components.tmt_chow.ps21050d_hub import TmtChowHub


def _hub() -> TmtChowHub:
    return TmtChowHub(
        uuid="test-uuid",
        thing_name="test-thing",
        name="PS20005A test gate",
        endpoint="example.invalid",
        certificate_pem="",
        private_key="",
        source_tag="P9999999",
        product_type="104",
        device_type="PS20005A",
    )


def test_ps20005a_reuses_only_ps20005_family_and_capabilities() -> None:
    hub = _hub()

    assert hub.controller_type == "PS20005A"
    assert hub.controller_family == FAMILY_SWING
    assert CAPABILITY_PEDESTRIAN in hub.controller_capabilities
    assert hub.pedestrian_strategy == PEDESTRIAN_STRATEGY_PED_OPEN


def test_ps20005a_alias_does_not_enable_parameter_writes() -> None:
    hub = _hub()

    assert hub.parameter_write_schema_verified is False
