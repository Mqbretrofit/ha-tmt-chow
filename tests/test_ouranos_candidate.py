"""Regression tests for vendor uuid_type OURANOS detection."""

from __future__ import annotations

from types import SimpleNamespace

from custom_components.tmt_chow import _is_ouranos_probe_candidate
from custom_components.tmt_chow.const import CONF_UUID, CONF_UUID_TYPE, DOMAIN


class _FakeConfigEntries:
    def __init__(self, entries: list[SimpleNamespace]) -> None:
        self._entries = entries

    def async_entries(self, domain: str):
        assert domain == DOMAIN
        return self._entries


def _hass_for(uuid: str, uuid_type: str):
    entry = SimpleNamespace(data={CONF_UUID: uuid, CONF_UUID_TYPE: uuid_type})
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
    assert _is_ouranos_probe_candidate(_hass_for(uuid, ""), hub) is True


def test_identifier_length_alone_is_not_transport_evidence() -> None:
    uuid = "12345678901234567890"
    hub = SimpleNamespace(uuid=uuid, configured_controller_type="PS25142")
    assert _is_ouranos_probe_candidate(_hass_for(uuid, ""), hub) is False
