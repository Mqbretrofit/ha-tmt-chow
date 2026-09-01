"""Diagnostic sensors for TMT Chow."""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import TmtChowEntity
from .hub import TmtChowHub


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    hub: TmtChowHub = hass.data[DOMAIN][entry.entry_id]
    if hub.supports_battery:
        async_add_entities([TmtBatterySensor(hub)])


class TmtBatterySensor(TmtChowEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_translation_key = "battery"

    def __init__(self, hub: TmtChowHub) -> None:
        super().__init__(hub)
        self._attr_unique_id = f"{hub.uuid}_battery"

    @property
    def native_value(self) -> int | None:
        return self.hub.battery_percent
