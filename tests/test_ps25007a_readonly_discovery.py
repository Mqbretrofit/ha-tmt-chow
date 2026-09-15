"""Tests for the PS25007/PS25007A read-only Shadow discovery sensors."""

from types import SimpleNamespace

from custom_components.tmt_chow.sensor import (
    _PS25007A_SHADOW_PARAMETER_COUNT,
    _is_ps25007a_discovery_target,
    _parse_ps25007a_shadow_parameters,
)


OBSERVED_PS25007A_DEV_PARAM = "1,3,0,3,3,3,11,1,0,1,0,2,3,0,0,0,0"


def test_ps25007a_observed_shadow_frame_parses_exactly() -> None:
    values = _parse_ps25007a_shadow_parameters(OBSERVED_PS25007A_DEV_PARAM)

    assert values == (1, 3, 0, 3, 3, 3, 11, 1, 0, 1, 0, 2, 3, 0, 0, 0, 0)
    assert len(values) == _PS25007A_SHADOW_PARAMETER_COUNT


def test_ps25007a_discovery_parser_rejects_unverified_shapes() -> None:
    assert _parse_ps25007a_shadow_parameters(None) is None
    assert _parse_ps25007a_shadow_parameters("1,2,3") is None
    assert _parse_ps25007a_shadow_parameters(
        "1,3,0,3,3,3,11,1,0,1,0,2,3,0,0,0,not-a-number"
    ) is None


def test_ps25007_configured_identity_enables_discovery_before_live_alias() -> None:
    configured_only = SimpleNamespace(
        controller_type="PS25007",
        configured_controller_type="PS25007",
    )
    live_alias = SimpleNamespace(
        controller_type="PS25007A",
        configured_controller_type="PS25007",
    )
    unrelated = SimpleNamespace(
        controller_type="PS21053C",
        configured_controller_type="PS21053C",
    )

    assert _is_ps25007a_discovery_target(configured_only) is True
    assert _is_ps25007a_discovery_target(live_alias) is True
    assert _is_ps25007a_discovery_target(unrelated) is False
