"""Diagnostic sensors for TMT Chow."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import ATTR_DEV_PARAM, DOMAIN
from .controller_types import is_known_non_gate_controller
from .entity import TmtChowEntity
from .hub import TmtChowHub

_PS25007_CONFIGURED_TYPE = "PS25007"
_PS25007A_CONTROLLER_TYPE = "PS25007A"
_PS25007A_SHADOW_PARAMETER_COUNT = 17


def _parse_ps25007a_shadow_parameters(raw: Any) -> tuple[int, ...] | None:
    """Parse the observed 17-value PS25007A Shadow DEV PARAM payload.

    This deliberately parses only the already-reported Shadow value. It does not
    select a parameter codec, authorize writes, or trigger any MQTT command.
    """
    if not isinstance(raw, str):
        return None

    tokens = [token.strip() for token in raw.split(",")]
    if len(tokens) != _PS25007A_SHADOW_PARAMETER_COUNT or any(
        not token for token in tokens
    ):
        return None

    try:
        return tuple(int(token, 10) for token in tokens)
    except ValueError:
        return None


def _is_ps25007a_discovery_target(hub: TmtChowHub) -> bool:
    """Return whether this entry can represent the observed PS25007A variant.

    The cloud account reports PS25007 while live DEV INFO reports PS25007A. The
    configured identity is included so the diagnostic entities are not lost to
    a startup race before the first Shadow response updates controller_type.
    """
    return (
        hub.controller_type == _PS25007A_CONTROLLER_TYPE
        or hub.configured_controller_type == _PS25007_CONFIGURED_TYPE
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    hub: TmtChowHub = hass.data[DOMAIN][entry.entry_id]
    if is_known_non_gate_controller(hub.controller_type):
        return

    entities: list[SensorEntity] = [TmtBatterySensor(hub)]
    if _is_ps25007a_discovery_target(hub):
        entities.extend(
            TmtPs25007aParameterSensor(hub, index)
            for index in range(_PS25007A_SHADOW_PARAMETER_COUNT)
        )
    async_add_entities(entities)


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


class TmtPs25007aParameterSensor(TmtChowEntity, SensorEntity):
    """Expose one raw PS25007A Shadow parameter for safe discovery mapping."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:numeric"

    def __init__(self, hub: TmtChowHub, index: int) -> None:
        super().__init__(hub)
        self._index = index
        wire_position = index + 1
        self._attr_name = f"PS25007A parameter {wire_position:02d}"
        self._attr_unique_id = f"{hub.uuid}_ps25007a_parameter_{wire_position:02d}"

    @property
    def available(self) -> bool:
        return (
            self.hub.available
            and _parse_ps25007a_shadow_parameters(
                self.hub.attributes.get(ATTR_DEV_PARAM)
            )
            is not None
        )

    @property
    def native_value(self) -> int | None:
        values = _parse_ps25007a_shadow_parameters(
            self.hub.attributes.get(ATTR_DEV_PARAM)
        )
        if values is None:
            return None
        return values[self._index]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "wire_position": self._index + 1,
            "discovery_mode": "shadow_read_only",
            "write_supported": False,
        }
