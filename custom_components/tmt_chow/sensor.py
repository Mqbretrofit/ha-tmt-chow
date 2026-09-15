"""Diagnostic sensors for TMT Chow."""

from __future__ import annotations

from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .controller_types import is_known_non_gate_controller
from .entity import TmtChowEntity
from .hub import TmtChowHub

_PS25007A_TEMP_MAPPER_PARAMETER_COUNT = 17


def _remove_temporary_ps25007a_mapper_entities(
    hass: HomeAssistant,
    hub: TmtChowHub,
) -> None:
    """Remove beta.6 raw mapper entities now replaced by real selectors."""
    registry = er.async_get(hass)
    for wire_position in range(1, _PS25007A_TEMP_MAPPER_PARAMETER_COUNT + 1):
        unique_id = f"{hub.uuid}_ps25007a_parameter_{wire_position:02d}"
        entity_id = registry.async_get_entity_id(SENSOR_DOMAIN, DOMAIN, unique_id)
        if entity_id is not None:
            registry.async_remove(entity_id)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    hub: TmtChowHub = hass.data[DOMAIN][entry.entry_id]
    _remove_temporary_ps25007a_mapper_entities(hass, hub)
    if is_known_non_gate_controller(hub.controller_type):
        return
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
