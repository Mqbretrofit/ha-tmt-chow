"""Regression tests for PS19001 stale parameter entity cleanup."""

from __future__ import annotations

from types import SimpleNamespace

import custom_components.tmt_chow as integration
from custom_components.tmt_chow.ps21050d_hub import TmtChowHub


def _hub(device_type: str = "PS19001") -> TmtChowHub:
    return TmtChowHub(
        uuid="ABCDEFGHIJKLMNOPQRST",
        thing_name="test-thing",
        name="Test gate",
        endpoint="example.invalid",
        certificate_pem="",
        private_key="",
        source_tag="P9999999",
        product_type="108",
        device_type=device_type,
    )


class _Registry:
    def __init__(self, *, matching_entry: bool = True) -> None:
        self.matching_entry = matching_entry
        self.removed: list[str] = []

    def async_get_entity_id(self, domain: str, platform: str, unique_id: str):
        assert domain == "select"
        assert platform == "tmt_chow"
        return f"select.{unique_id.lower()}"

    def async_get(self, entity_id: str):
        return SimpleNamespace(
            config_entry_id="entry-1" if self.matching_entry else "another-entry"
        )

    def async_remove(self, entity_id: str) -> None:
        self.removed.append(entity_id)


def test_removes_only_four_obsolete_ps19001_parameter_entities(monkeypatch) -> None:
    registry = _Registry()
    monkeypatch.setattr(integration.er, "async_get", lambda hass: registry)

    integration._remove_legacy_ps19001_parameter_entities(
        object(),
        SimpleNamespace(entry_id="entry-1"),
        _hub(),
    )

    assert registry.removed == [
        f"select.abcdefghijklmnopqrst_parameter_{number}"
        for number in range(20, 24)
    ]


def test_does_not_remove_entities_from_another_config_entry(monkeypatch) -> None:
    registry = _Registry(matching_entry=False)
    monkeypatch.setattr(integration.er, "async_get", lambda hass: registry)

    integration._remove_legacy_ps19001_parameter_entities(
        object(),
        SimpleNamespace(entry_id="entry-1"),
        _hub(),
    )

    assert registry.removed == []


def test_does_not_touch_non_ps19001_controller(monkeypatch) -> None:
    registry = _Registry()
    monkeypatch.setattr(integration.er, "async_get", lambda hass: registry)

    integration._remove_legacy_ps19001_parameter_entities(
        object(),
        SimpleNamespace(entry_id="entry-1"),
        _hub("PS21053"),
    )

    assert registry.removed == []
