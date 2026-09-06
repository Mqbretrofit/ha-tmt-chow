"""Regression coverage for the PS20040/PS20040D live alias."""

from custom_components.tmt_chow.controller_types import CAPABILITY_PEDESTRIAN
from custom_components.tmt_chow.protocol import decode_dev_status
from custom_components.tmt_chow.ps21050d_hub import TmtChowHub


def _hub() -> TmtChowHub:
    return TmtChowHub(
        uuid="test-uuid",
        thing_name="test-thing",
        name="Test PS20040D gate",
        endpoint="example.invalid",
        certificate_pem="",
        private_key="",
        source_tag="P9999999",
        product_type="112",
        device_type="PS20040",
    )


def test_ps20040d_live_alias_keeps_ps20040_family_pedestrian_and_write_codec() -> None:
    hub = _hub()

    # Account/configured model is PS20040; live DEV INFO later reports PS20040D.
    hub._set_controller_type("PS20040D")

    assert hub.configured_controller_type == "PS20040"
    assert hub.controller_type == "PS20040D"
    assert hub.controller_family == "sliding"
    assert CAPABILITY_PEDESTRIAN in hub.controller_capabilities

    # The exact app/live alias uses the PS20040 RP,1/WP,1 schema and keeps the
    # base hub's read-before-write plus mandatory read-back verification.
    assert hub.parameter_model_type == "PS20040"
    assert hub.parameter_model_source == "apk_ps20040_alias"
    assert hub.parameter_schema_verified is True
    assert hub.parameter_write_schema_verified is True
    assert hub.supports_parameters is True


def test_ff_battery_status_is_not_exposed_as_127_percent() -> None:
    status = decode_dev_status("00,FF,A0,00,40,00,80,C0,00")

    assert status.position == 0
    assert status.battery_percent is None


def test_valid_battery_percentage_is_preserved() -> None:
    status = decode_dev_status("00,64,A0,00")

    assert status.battery_percent == 100
