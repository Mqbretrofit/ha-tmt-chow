"""Regression tests for vendor uuid_type OURANOS detection."""

from __future__ import annotations

from types import SimpleNamespace

from custom_components.tmt_chow import (
    _is_known_ouranos_candidate,
    _is_ouranos_probe_candidate,
    _ouranos_probe_status_command,
)
from custom_components.tmt_chow.const import (
    CONF_PROPOSAL,
    CONF_UUID,
    CONF_UUID_TYPE,
    DOMAIN,
)


class _FakeConfigEntries:
    def __init__(self, entries: list[SimpleNamespace]) -> None:
        self._entries = entries

    def async_entries(self, domain: str):
        assert domain == DOMAIN
        return self._entries


def _hass_for(uuid: str, uuid_type: str, proposal=None):
    entry = SimpleNamespace(
        data={
            CONF_UUID: uuid,
            CONF_UUID_TYPE: uuid_type,
            CONF_PROPOSAL: proposal,
        }
    )
    return SimpleNamespace(config_entries=_FakeConfigEntries([entry]))


def test_uuid_type_1_is_ouranos_probe_candidate() -> None:
    uuid = "12345678901234567890"
    hub = SimpleNamespace(uuid=uuid, configured_controller_type="PS25142")
    assert _is_ouranos_probe_candidate(_hass_for(uuid, "1"), hub) is True


def test_wbt_uuid_type_is_not_ouranos_for_unknown_controller() -> None:
    uuid = "12345678901234567890"
    hub = SimpleNamespace(uuid=uuid, configured_controller_type="PS25142")
    assert _is_ouranos_probe_candidate(_hass_for(uuid, "5"), hub) is False


def test_legacy_ps19001_fallback_remains_available() -> None:
    uuid = "12345678901234567890"
    hub = SimpleNamespace(uuid=uuid, configured_controller_type="PS19001")
    assert _is_known_ouranos_candidate(hub) is True


def test_identifier_length_alone_is_not_transport_evidence() -> None:
    uuid = "12345678901234567890"
    hub = SimpleNamespace(uuid=uuid, configured_controller_type="PS25142")
    assert _is_ouranos_probe_candidate(_hass_for(uuid, ""), hub) is False


def test_uart_v3_autoproduct_uses_rs_probe() -> None:
    uuid = "12345678901234567890"
    hub = SimpleNamespace(uuid=uuid, configured_controller_type="PS25142")
    hass = _hass_for(uuid, "1", {"uartVer": "V3.0"})
    assert _ouranos_probe_status_command(hass, hub) == "RS"


def test_unknown_uart_version_keeps_read_status_probe() -> None:
    uuid = "12345678901234567890"
    hub = SimpleNamespace(uuid=uuid, configured_controller_type="PS25142")
    hass = _hass_for(uuid, "1", {"uartVer": "V2.0"})
    assert _ouranos_probe_status_command(hass, hub) == "READ_STATUS"


def test_verified_ps19001_keeps_read_status_even_with_v3_proposal() -> None:
    uuid = "12345678901234567890"
    hub = SimpleNamespace(uuid=uuid, configured_controller_type="PS19001")
    hass = _hass_for(uuid, "1", {"uartVer": "V3.0"})
    assert _ouranos_probe_status_command(hass, hub) == "READ_STATUS"
